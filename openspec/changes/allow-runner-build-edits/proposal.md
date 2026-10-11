# Allow runner BUILD to edit files in its workspace

## Problem
BUILD runs `claude -p` headless with the runner's settings, which list only deny rules. In `-p` mode a
tool that needs approval is refused, so Edit and Write are always refused; only sandboxed shell commands
are auto-allowed. A build passes only if the agent falls back to shell writes. On 09-28 two runs failed
their first attempt this way, and on 10-11 run `fix-runner-decision-edit-error` failed both attempts
("output.json is missing") with the agent reporting it was not allowed to edit `bot.py` or `tests/`.

## Goals
- BUILD can use its file-edit tools inside its own workspace, every time.
- Edits outside the workspace stay blocked, and the pre-run self-test proves it.

## Non-goals
- Changing the Hermes backend, the shell sandbox, or what the agent may read.

## Success criteria
- The rendered runner settings set `defaultMode: acceptEdits` and deny edits to the main checkout, the
  snapshot folder, `~/.seb-runner`, `~/.hermes`, `~/.claude`, `~/.ssh`, `~/.aws` and `~/.config`.
- The Claude self-test fails closed if the Write tool can create a file in `~/.seb-runner`.
