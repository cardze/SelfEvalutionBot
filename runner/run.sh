#!/bin/bash
# launchd entrypoint for the autonomous feedback runner (see runner/launchd/com.seb.runner.plist.template).
# Holds an exclusive lock, then runs one tick of runner/runner.py. Exits quietly if another tick is running.
set -u
MAIN="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER_HOME="$HOME/.seb-runner"
LOCK="$RUNNER_HOME/lock"
LOG="$RUNNER_HOME/logs/runner.log"
PY="${BOT_PYTHON:-$(command -v python3)}"
mkdir -p "$RUNNER_HOME/logs"

if ! mkdir "$LOCK" 2>/dev/null; then
  holder=$(cat "$LOCK/pid" 2>/dev/null || true)
  if [[ -n "$holder" ]] && kill -0 "$holder" 2>/dev/null; then
    exit 0   # another tick is running
  fi
  echo "$(date '+%F %T') removing stale lock (pid ${holder:-unknown})" >> "$LOG"
  rm -rf "$LOCK"
  mkdir "$LOCK" 2>/dev/null || exit 0
fi
echo $$ > "$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

cd "$MAIN" && "$PY" -m runner.runner >> "$LOG" 2>&1
