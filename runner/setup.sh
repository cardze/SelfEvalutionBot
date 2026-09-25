#!/bin/bash
# One-time setup and maintenance for the autonomous feedback runner.
#
#   runner/setup.sh store-token        save the OAuth token from the clipboard (never printed)
#   runner/setup.sh render-settings    write ~/.seb-runner/runner-settings.json
#   runner/setup.sh selftest           run the isolation self-test now
#   runner/setup.sh install-agents     install + load the bot and runner launchd agents
#   runner/setup.sh uninstall-agents   unload + remove both launchd agents
set -euo pipefail

MAIN="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_HOME="$HOME/.seb-runner"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PY="${BOT_PYTHON:-$(command -v python3)}"
DOMAIN="gui/$(id -u)"
LABELS=(com.seb.bot com.seb.runner)

mkdir -p "$RUNNER_HOME/logs"
chmod 700 "$RUNNER_HOME"

cmd_store_token() {
  local tmp="$RUNNER_HOME/oauth_token.tmp"
  (umask 077; pbpaste | tr -d '\n\r ' > "$tmp")
  if [[ "$(head -c 13 "$tmp")" != "sk-ant-oat01-" ]]; then
    rm -f "$tmp"
    echo "Clipboard does not contain a Claude OAuth token (expected prefix sk-ant-oat01-). Nothing written." >&2
    exit 1
  fi
  local n; n=$(wc -c < "$tmp" | tr -d ' ')
  if (( n < 60 || n > 400 )); then
    rm -f "$tmp"
    echo "Token length $n looks wrong. Nothing written." >&2
    exit 1
  fi
  mv "$tmp" "$RUNNER_HOME/oauth_token"
  chmod 600 "$RUNNER_HOME/oauth_token"
  pbcopy </dev/null
  echo "Stored token ($n characters, prefix ok) in $RUNNER_HOME/oauth_token (mode 600). Clipboard cleared."
}

cmd_render_settings() {
  (cd "$MAIN" && "$PY" -m runner.templates settings)
}

cmd_selftest() {
  cmd_render_settings >/dev/null
  (cd "$MAIN" && "$PY" -m runner.selftest)
}

cmd_install_agents() {
  mkdir -p "$AGENTS_DIR"
  (cd "$MAIN" && "$PY" -m runner.templates plists "$AGENTS_DIR") >/dev/null
  for label in "${LABELS[@]}"; do
    launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
    plutil -lint "$AGENTS_DIR/$label.plist" >/dev/null
    launchctl bootstrap "$DOMAIN" "$AGENTS_DIR/$label.plist"
    echo "Loaded $label"
  done
  echo "Bot status:"; launchctl print "$DOMAIN/com.seb.bot" | grep -E "state =|pid =" || true
}

cmd_uninstall_agents() {
  for label in "${LABELS[@]}"; do
    launchctl bootout "$DOMAIN/$label" 2>/dev/null && echo "Unloaded $label" || echo "$label was not loaded"
    rm -f "$AGENTS_DIR/$label.plist"
  done
}

case "${1:-}" in
  store-token)      cmd_store_token ;;
  render-settings)  cmd_render_settings ;;
  selftest)         cmd_selftest ;;
  install-agents)   cmd_install_agents ;;
  uninstall-agents) cmd_uninstall_agents ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
