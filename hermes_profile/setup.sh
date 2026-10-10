#!/bin/bash
# Run SelfEvaluationBot inside a Hermes Agent gateway (change move-bot-into-hermes).
#
#   hermes_profile/setup.sh install     create/refresh the `seb` profile, plugin, .env and settings
#   hermes_profile/setup.sh cron        schedule the feedback runner hourly in Hermes cron (replaces launchd)
#   hermes_profile/setup.sh start       stop the launchd bot, install + start the `seb` gateway service
#   hermes_profile/setup.sh restart     restart the `seb` gateway (picks up merged code)
#   hermes_profile/setup.sh sync        refresh the plugin and install its Python dependencies (runner, on merge)
#   hermes_profile/setup.sh uninstall   stop the gateway service and remove the cron job (rollback)
set -euo pipefail

MAIN="$(cd "$(dirname "$0")/.." && pwd)"
PROFILE="${HERMES_PROFILE:-seb}"
HOME_DIR="$HOME/.hermes/profiles/$PROFILE"
RUNNER_HOME="$HOME/.seb-runner"
PY="${BOT_PYTHON:-$MAIN/.venv/bin/python}"
JOB=seb-runner

need_hermes() {
  command -v hermes >/dev/null || { echo "hermes not found. Install: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" >&2; exit 1; }
}

# Read KEY from the main checkout's .env without printing it.
main_env() {
  grep -E "^(export )?$1=" "$MAIN/.env" 2>/dev/null | tail -1 | sed -E "s/^(export )?$1=//; s/^[\"']//; s/[\"']$//"
}

set_profile_env() {  # set_profile_env KEY VALUE  (replaces any existing line, never echoes VALUE)
  local env="$HOME_DIR/.env"
  touch "$env" && chmod 600 "$env"
  grep -v -E "^$1=" "$env" > "$env.tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$env.tmp"
  mv "$env.tmp" "$env"
  chmod 600 "$env"
}

cmd_install() {
  need_hermes
  [[ -f "$MAIN/.env" ]] || { echo "No $MAIN/.env; create it from .env.example first." >&2; exit 1; }
  local token admin
  token=$(main_env TELEGRAM_BOT_TOKEN); admin=$(main_env ADMIN_USER_ID)
  [[ -n "$token" && -n "$admin" ]] || { echo "TELEGRAM_BOT_TOKEN and ADMIN_USER_ID must be set in $MAIN/.env" >&2; exit 1; }

  hermes profile list 2>/dev/null | grep -qw "$PROFILE" || hermes profile create "$PROFILE"
  mkdir -p "$HOME_DIR/plugins"
  chmod 700 "$HOME_DIR"
  cp "$MAIN/hermes_profile/SOUL.md" "$HOME_DIR/SOUL.md"
  copy_plugin

  set_profile_env TELEGRAM_BOT_TOKEN "$token"
  set_profile_env TELEGRAM_ALLOWED_USERS "$admin"   # only the owner chats with the agent
  set_profile_env ADMIN_USER_ID "$admin"
  set_profile_env SEB_MAIN "$MAIN"
  # Problem events for the runner's suggestions (same file launchd's com.seb.bot writes to).
  set_profile_env SEB_SIGNALS_FILE "$RUNNER_HOME/logs/signals.jsonl"
  for key in POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
    value=$(main_env "$key"); [[ -n "$value" ]] && set_profile_env "$key" "$value"
  done

  hermes -p "$PROFILE" config set unauthorized_dm_behavior decline >/dev/null
  hermes -p "$PROFILE" config set unauthorized_dm_decline_message \
    "Hi! Chat is only open to the bot's owner. You can use /feedback, /remind, /reminders, /meal and /calc." >/dev/null
  # Enabling adds the plugin to Hermes's dependency set; `pm install` syncs it (also on a re-run,
  # when the plugin was already enabled).
  hermes -p "$PROFILE" plugins enable seb
  hermes -p "$PROFILE" pm install

  echo "Profile $PROFILE ready at $HOME_DIR (secrets copied into its .env, not printed)."
  echo "Next: pick a model for the owner's chats:  hermes -p $PROFILE model"
  echo "Then: hermes_profile/setup.sh cron && hermes_profile/setup.sh start"
}

cmd_cron() {
  need_hermes
  [[ -x "$PY" ]] || { echo "Runner Python $PY not found; set BOT_PYTHON" >&2; exit 1; }
  mkdir -p "$HOME_DIR/scripts"
  cat > "$HOME_DIR/scripts/$JOB.sh" <<SCRIPT
#!/bin/bash
# Hourly SelfEvaluationBot feedback runner tick (written by hermes_profile/setup.sh). Silent: the
# runner reports to Telegram itself and logs to ~/.seb-runner/logs/runner.log.
export BOT_PYTHON="$PY"
"$MAIN/runner/run.sh" >/dev/null 2>&1
SCRIPT
  chmod 700 "$HOME_DIR/scripts/$JOB.sh"
  hermes -p "$PROFILE" cron list 2>/dev/null | grep -q "$JOB" && hermes -p "$PROFILE" cron remove "$JOB" >/dev/null 2>&1 || true
  hermes -p "$PROFILE" cron create "every 1h" --no-agent --script "$JOB.sh" --deliver local --name "$JOB"

  # Hermes now owns scheduling and restarts: switch the runner over and retire the launchd runner job.
  mkdir -p "$RUNNER_HOME"; touch "$RUNNER_HOME/config.env"
  grep -v -E '^(BOT_SERVICE|HERMES_PROFILE|HERMES_PYTHON)=' "$RUNNER_HOME/config.env" > "$RUNNER_HOME/config.env.tmp" || true
  {
    echo "BOT_SERVICE=hermes"
    echo "HERMES_PROFILE=$PROFILE"
    # The merge step restarts the gateway with this binary; cron's PATH may not include it.
    grep -q '^HERMES_BIN=' "$RUNNER_HOME/config.env" || echo "HERMES_BIN=$(command -v hermes)"
  } >> "$RUNNER_HOME/config.env.tmp"
  mv "$RUNNER_HOME/config.env.tmp" "$RUNNER_HOME/config.env"
  launchctl bootout "gui/$(id -u)/com.seb.runner" 2>/dev/null && echo "Unloaded launchd com.seb.runner" || true
  echo "Runner scheduled in Hermes cron ($JOB, every 1h)."
}

# Copy the plugin shim into the profile. Its python_dependencies are generated from the bot's
# requirements.txt minus python-telegram-bot (the gateway pins its own), so Hermes's package
# manager installs exactly what the bot needs; nothing is pip-installed into Hermes by hand.
copy_plugin() {
  local dest="$HOME_DIR/plugins/seb"
  mkdir -p "$HOME_DIR/plugins"
  rm -rf "$dest"
  cp -R "$MAIN/hermes_plugin/seb" "$dest"
  sed -i.bak '/^python_dependencies:/,$d' "$dest/plugin.yaml" && rm -f "$dest/plugin.yaml.bak"
  {
    echo "python_dependencies:"
    grep -v -E '^[[:space:]]*(#|$)' "$MAIN/requirements.txt" \
      | grep -v -i -E '^python[-_]telegram[-_]bot([^a-z0-9_-]|$)' \
      | sed -E 's/[[:space:]]*#.*$//; s/.*/  - "&"/'
  } >> "$dest/plugin.yaml"
}

cmd_sync() {
  need_hermes
  copy_plugin
  hermes -p "$PROFILE" pm install
}

cmd_start() {
  need_hermes
  launchctl bootout "gui/$(id -u)/com.seb.bot" 2>/dev/null && echo "Unloaded launchd com.seb.bot (one poller per token)" || true
  hermes -p "$PROFILE" gateway install
  hermes -p "$PROFILE" gateway start
  hermes -p "$PROFILE" gateway status || true
}

cmd_restart() {
  need_hermes
  hermes -p "$PROFILE" gateway restart
}

cmd_uninstall() {
  need_hermes
  hermes -p "$PROFILE" cron remove "$JOB" 2>/dev/null || true
  hermes -p "$PROFILE" gateway stop 2>/dev/null || true
  hermes -p "$PROFILE" gateway uninstall 2>/dev/null || true
  if [[ -f "$RUNNER_HOME/config.env" ]]; then
    grep -v -E '^BOT_SERVICE=' "$RUNNER_HOME/config.env" > "$RUNNER_HOME/config.env.tmp" || true
    mv "$RUNNER_HOME/config.env.tmp" "$RUNNER_HOME/config.env"
  fi
  echo "Hermes gateway and cron job removed. Bring back launchd with: runner/setup.sh install-agents"
}

case "${1:-}" in
  install)   cmd_install ;;
  cron)      cmd_cron ;;
  start)     cmd_start ;;
  restart)   cmd_restart ;;
  sync)      cmd_sync ;;
  uninstall) cmd_uninstall ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
