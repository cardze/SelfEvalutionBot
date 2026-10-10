#!/bin/bash
# One-time setup and maintenance for the autonomous feedback runner.
#
#   runner/setup.sh store-token        save the OAuth token from the clipboard (never printed)
#   runner/setup.sh render-settings    write ~/.seb-runner/runner-settings.json
#   runner/setup.sh selftest           run the isolation self-test now
#   runner/setup.sh install-agents     install + load the bot and runner launchd agents
#   runner/setup.sh uninstall-agents   unload + remove both launchd agents
#   runner/setup.sh hermes-profile     create/refresh the seb-runner Hermes profile (Hermes backend)
#   runner/setup.sh hermes-sandbox     build the sandbox image, internal network and PyPI egress proxy
#   runner/setup.sh use-backend <claude|hermes>   choose the agent backend in config.env
set -euo pipefail

MAIN="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_HOME="$HOME/.seb-runner"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PY="${BOT_PYTHON:-$(command -v python3)}"
DOMAIN="gui/$(id -u)"
LABELS=(com.seb.bot com.seb.runner)
SANDBOX_IMAGE=seb-runner-sandbox:latest
SANDBOX_NETWORK=seb-runner-sandbox
EGRESS_NAME=seb-runner-egress
SQUID_IMAGE=ubuntu/squid:6.10-24.04_edge

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

cmd_hermes_profile() {
  command -v hermes >/dev/null || { echo "hermes not found. Install: curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash" >&2; exit 1; }
  local cfg; cfg=$(cd "$MAIN" && "$PY" -m runner.templates hermes-profile)
  local home; home=$(dirname "$cfg")
  chmod 700 "$home"
  touch "$home/.env" && chmod 600 "$home/.env"
  echo "Rendered $cfg"
  echo "Next: log in a provider for this profile (keys stay on the host, never in the sandbox):"
  echo "  HERMES_HOME=$home hermes auth add <provider>     # or put the API key in $home/.env"
  echo "Then set HERMES_PROVIDER / HERMES_MODEL in $RUNNER_HOME/config.env if you don't want Hermes's auto-detection."
}

cmd_hermes_sandbox() {
  command -v docker >/dev/null || { echo "docker not found (install Docker Desktop)" >&2; exit 1; }
  docker build -t "$SANDBOX_IMAGE" "$MAIN/runner/hermes"
  docker network inspect "$SANDBOX_NETWORK" >/dev/null 2>&1 || docker network create --internal "$SANDBOX_NETWORK"
  docker rm -f "$EGRESS_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$EGRESS_NAME" --restart unless-stopped \
    -v "$MAIN/runner/hermes/squid.conf:/etc/squid/squid.conf:ro" "$SQUID_IMAGE" >/dev/null
  docker network connect "$SANDBOX_NETWORK" "$EGRESS_NAME"
  echo "Sandbox ready: image $SANDBOX_IMAGE, internal network $SANDBOX_NETWORK, egress proxy $EGRESS_NAME (PyPI only)."
}

cmd_use_backend() {
  local backend="${1:-}"
  [[ "$backend" == claude || "$backend" == hermes ]] || { echo "usage: runner/setup.sh use-backend <claude|hermes>" >&2; exit 2; }
  local env="$RUNNER_HOME/config.env"
  touch "$env"
  grep -v '^AGENT_BACKEND=' "$env" > "$env.tmp" || true
  echo "AGENT_BACKEND=$backend" >> "$env.tmp"
  mv "$env.tmp" "$env"
  echo "Agent backend: $backend (in $env). Run: runner/setup.sh selftest"
}

case "${1:-}" in
  store-token)      cmd_store_token ;;
  render-settings)  cmd_render_settings ;;
  selftest)         cmd_selftest ;;
  install-agents)   cmd_install_agents ;;
  uninstall-agents) cmd_uninstall_agents ;;
  hermes-profile)   cmd_hermes_profile ;;
  hermes-sandbox)   cmd_hermes_sandbox ;;
  use-backend)      cmd_use_backend "${2:-}" ;;
  *) sed -n '2,12p' "$0"; exit 2 ;;
esac
