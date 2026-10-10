## Why

The admin wants the whole bot, not just the runner's agent, to live in **Hermes Agent** (Nous
Research): one agent that talks on Telegram, runs the feedback loop on a schedule, and can be
inspected in `hermes dashboard`. Today the bot is a standalone `python-telegram-bot` process
(`bot.py`, launchd `com.seb.bot`) and the loop is a separate launchd job (`com.seb.runner`).
Hermes already provides the pieces this project re-implements — a Telegram gateway with an owner
allowlist, a cron scheduler, a plugin system, profiles and a web dashboard — so moving onto it puts
the bot's "evolve by feedback" loop inside a self-improving agent instead of beside it.

This change builds on `add-hermes-agent-backend` (runner agent runs on Hermes in a Docker sandbox).

## What Changes

- New **Hermes plugin** `hermes_plugin/seb/` (loaded into a dedicated Hermes profile `seb`):
  - wires every existing Telegram handler (`/start`, `/help`, `/feedback` + `/cancel`, `/calc`,
    `/meal`, `/remind`, `/reminders`, clarification buttons and replies, runner ✅/❌/💬 buttons and
    notes) into the Hermes gateway's own Telegram application, ahead of Hermes's core handlers, so
    every public user keeps exactly today's commands;
  - starts the reminder delivery loop and initializes the database when the gateway connects;
  - registers the commands as Hermes slash commands so they appear in the Telegram `/` menu;
  - gives the **owner's** Hermes agent read-only tools over the bot's data
    (`seb_feedback_queue`, `seb_runner_status`), gated on the gateway-reported sender id.
- `bot.py` keeps its handlers but exposes them through `register_handlers(application)` and
  `start_background(application)`; `python bot.py` still works as the rollback path.
- New **profile assets** `hermes_profile/`: `SOUL.md` and `hermes_profile/setup.sh` (configures the
  Telegram gateway, declines unauthorized users with a pointer to the bot commands, enables the plugin) with `install`, `cron`, `start`, `restart`, `uninstall`.
- The **feedback loop moves into Hermes cron**: a script-only (no-LLM) job runs `runner/run.sh`
  hourly in the `seb` profile instead of launchd `com.seb.runner`.
- The runner gains `BOT_SERVICE=launchd|hermes`: with `hermes`, a merge installs new requirements
  into Hermes's environment through its package manager (never touching its `python-telegram-bot`) and restarts the `seb` profile's standalone Hermes gateway
  in a detached process after the run is recorded as merged.
- Chatting with the agent stays **owner-only** (Hermes's allowlist); everyone else can use the bot's
  commands but gets a polite decline for free text, as today.

## Capabilities

### New Capabilities
- `hermes-bot-host`: running the Telegram bot inside the Hermes gateway (handler wiring and
  precedence, background loop, command menu, owner-only agent tools, profile and setup, cron-driven
  runner, gateway restart after merge).

### Modified Capabilities
- (none) — `bot-supervision` keeps describing the launchd mode, which remains the default and the
  rollback path; `hermes-bot-host` states the Hermes mode.

## Non-goals

- Re-writing the bot's features as LLM-driven skills; the deterministic handlers are kept.
- Letting non-owner users chat with the agent.
- Removing `bot.py`, `runner/launchd/` or the Claude runner backend (a follow-up, once the Hermes
  mode has run for a while).

## Success criteria

- With the plugin loaded, every command behaves as it does under `bot.py` (same handler code).
- The existing suite plus new plugin tests pass without Hermes installed.
- `hermes_profile/setup.sh install` on the admin's Mac yields a `seb` profile whose gateway answers
  `/feedback` for any user, chats only with the admin, and whose cron runs the runner hourly.
