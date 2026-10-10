## Why

The autonomous feedback runner (`runner/`) is the loop that makes this bot "evolve by users'
feedback": PLAN turns the admin's feedback into an OpenSpec change, BUILD implements it, and the admin
approves the merge in Telegram. Today every agent step is hard-wired to Claude Code (`claude -p`),
its OAuth token, its `--agents` JSON and its built-in sandbox.

The admin wants the loop to run on **Hermes Agent** (Nous Research, `NousResearch/hermes-agent`),
an open-source, model-agnostic agent built around a self-improvement loop. Hermes can do the same
one-shot runs (`hermes chat -q … --format stream-json`), works with any provider (Nous Portal,
OpenRouter, Anthropic, OpenAI, local endpoints), and isolates tool execution in a Docker sandbox.
Moving the runner onto it removes the lock-in to one vendor's CLI and subscription token while
keeping the approval gate and the isolation guarantees the runner was built around.

## What Changes

- The runner gains a selectable **agent backend**: `AGENT_BACKEND=claude|hermes` in
  `~/.seb-runner/config.env`. `claude` (today's behaviour) stays the default until the admin has set
  up Hermes, so pulling this change does not break the hourly launchd run.
- A **Hermes backend** runs every agent step the runner starts — the isolation self-test, PLAN,
  BUILD and the sandboxed pytest verification — through `hermes chat --query-file -
  --format stream-json`, with a dedicated Hermes profile `seb-runner` (`~/.hermes/profiles/seb-runner`
  via `HERMES_HOME`; it shows up in `hermes dashboard`), and parses Hermes's JSONL events instead of Claude's stream-json.
- **Sandbox for Hermes**: tool calls (terminal, file and code tools) run in a fresh, hardened Docker
  container that sees only the workspace (mounted at `/workspace`), on an internal Docker network
  whose only way out is an allowlisting proxy for PyPI. The runner profile's `config.yaml` is
  rendered from `runner/hermes/config.template.yaml`; workspace files cannot change it.
- **Same agent definitions**: `.claude/agents/*.md` and `.claude/skills/*` are snapshotted from
  `main` into the Hermes profile as skills (`seb-agent-<name>`, `seb-<skill>`) and preloaded with
  `-s`, so the PLAN/BUILD flow (openspec-leader → planner / evaluator → coder) is unchanged.
- Hermes's persistent memory, skill writing, web, browser and messaging tools are **off** for runner
  runs (toolsets limited to `terminal,file,todo,delegation`; `--ignore-rules`), so nothing an agent
  learns in one run can steer a later run outside the reviewed `main` snapshot.
- `runner/setup.sh` gains `hermes-profile`, `hermes-sandbox` and `use-backend <name>` commands;
  README documents the switch and rollback.
- Prompts become backend-neutral: Python/pip commands come from the backend (`.venv/bin/python` for
  Claude, a container-local venv for Hermes) and a short Hermes appendix explains its tool names and
  delegation.

## Capabilities

### New Capabilities
- `runner-agent-backend`: selecting the agent backend, the Hermes run contract (command, profile,
  skills snapshot, event parsing, auth-failure reporting) and the Hermes sandbox guarantees.

### Modified Capabilities
- (none) — the existing `runner-isolation` and `autonomous-feedback-runner` requirements keep
  describing the Claude backend; `runner-agent-backend` states the equivalent guarantees for Hermes
  and requires the same self-test to pass before any Hermes agent run.

## Non-goals

- Replacing the Telegram bot (`bot.py`) with the Hermes messaging gateway, or moving reminders /
  feedback collection into Hermes skills.
- Letting Hermes keep memory or create skills between runner runs (a possible follow-up once there
  is a reviewed path for promoting learned skills into `main`).
- Removing the Claude backend.

## Success criteria

- With `AGENT_BACKEND=claude` (default) nothing changes; the full existing test suite passes.
- With `AGENT_BACKEND=hermes`, `runner/setup.sh selftest` prints `SELFTEST PASSED`, and an hourly
  tick plans, builds, verifies and sends the 🔀 merge request exactly as before.
- Unit tests cover the Hermes command line, environment, JSONL parsing, self-test and verification
  verdicts, skill snapshot and config parsing without needing Hermes, Docker or a database.

## Impact

- New: `runner/hermes.py`, `runner/hermes/config.template.yaml`, `runner/hermes/Dockerfile`,
  `runner/hermes/squid.conf`, `runner/prompts/hermes.md`, tests.
- Changed: `runner/config.py`, `runner/agent.py`, `runner/selftest.py`, `runner/verify.py`,
  `runner/runner.py`, `runner/snapshot.py`, `runner/templates.py`, `runner/setup.sh`,
  `runner/prompts/build.md`, `README.md`.
- Not changed: database schema, bot commands, `requirements.txt` (Hermes is installed on the host
  with its own installer, not imported by the bot).
