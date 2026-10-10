## Context

Facts about Hermes Agent (checked against `NousResearch/hermes-agent` main, 2026-10-09):

- The Telegram gateway uses python-telegram-bot 22.8. A plugin can call
  `ctx.register_platform_handler("telegram", factory)`; the factory receives the PTB `Application`
  at connect time and runs **before** Hermes registers its core handlers, so plugin handlers in the
  same group win first-match dispatch. Callback handlers must be pattern-scoped.
- `ctx.register_command(name, handler, description)` adds a slash command to `/help` and the
  Telegram `/` menu; built-in names (`help`, `new`, …) are rejected silently.
- `ctx.register_tool(name, toolset, schema, handler)` adds an agent tool. Inside the gateway,
  `gateway.session_context.get_session_env("HERMES_SESSION_USER_ID")` and
  `HERMES_SESSION_PLATFORM` give the sender identity set by the gateway, not by the model.
- Unauthorized DMs: `unauthorized_dm_behavior: pair | ignore | decline` plus
  `unauthorized_dm_decline_message`. `TELEGRAM_ALLOWED_USERS` is the owner allowlist.
- Plugins live in `$HERMES_HOME/plugins/<name>/` (`plugin.yaml` + `__init__.py` with
  `register(ctx)`), may declare `python_dependencies`, and are enabled with `hermes plugins enable`.
- Script-only cron: scripts must live in `$HERMES_HOME/scripts/`;
  `hermes cron create "every 1h" --no-agent --script X --deliver local --name N`. Empty stdout is
  a silent tick.
- One **host gateway** per machine (started from the `default` profile) serves every profile; a
  named profile gets no gateway of its own (`hermes -p seb gateway install|start|restart` is
  refused). The host is managed with `hermes -p default gateway restart`, which also makes it pick
  up a new or changed profile.

## Decisions

### B1. Keep the handlers, change the host
The bot's behaviour is deterministic and covered by tests; rewriting it as prompts would lose that.
`bot.py` gets two functions used by both hosts:
- `register_handlers(application)` — exactly the handler set and groups `main()` adds today.
- `start_background(application)` — the reminder delivery loop on the running event loop.
`main()` becomes: init DB → build app → `register_handlers` → `run_polling` (post_init →
`start_background`). Behaviour under `python bot.py` is unchanged.

### B2. The plugin (`hermes_plugin/seb/`)
- **Locating the code.** Setup copies the thin shim to `$HERMES_HOME/plugins/seb/` and writes
  `SEB_MAIN` into the profile `.env`; the shim reads `SEB_MAIN` (else its own path's
  `<MAIN>/hermes_plugin/seb` parent, for running it in place) and imports `<MAIN>/hermes_bot.py`,
  so merged code is picked up on the next gateway restart without reinstalling the plugin. `<MAIN>` is put on `sys.path` and its
  `.env` is loaded with `override=False`, so profile values win.
- **Telegram wiring** (`register_platform_handler("telegram", …)`): `db.init_database()`, then
  `bot.register_handlers(app)`, then `bot.start_background(app)` on the running loop. Our
  `CommandHandler`s and the `/feedback` `ConversationHandler` sit in group 0 ahead of Hermes's
  catch-all handlers; text that is part of a feedback conversation or a reply to a clarification /
  runner note is consumed by our handlers and never reaches the agent; everything else falls through
  to Hermes. Callback patterns `^run:`, `^sig:`, `^apv:`, `^clr:` are already scoped. The bot's error handler is added too, so problem events still reach the runner (`SEB_SIGNALS_FILE` is set in the profile `.env`).
- **Errors** in wiring are logged and leave Hermes running (Hermes isolates factory failures).
- **Menu.** `register_command` for `feedback`, `calc`, `meal`, `remind`, `reminders`, `cancel`
  with short handlers for non-Telegram surfaces (`calc` and `meal` work everywhere; the others
  answer "use this in Telegram"). On Telegram our PTB handlers answer first.
- **Owner tools** (toolset `seb`): `seb_feedback_queue` (actionable feedback, via
  `FeedbackService.get_actionable_feedback`) and `seb_runner_status` (in-flight run). Each handler
  returns an error unless the session is a non-messaging surface (CLI, dashboard, cron) or the
  gateway-reported sender is `ADMIN_USER_ID`. Read-only by design.

### B3. Profile `seb` and its config
`hermes_profile/setup.sh install` creates the profile and changes only the settings it needs in
`~/.hermes/profiles/seb/config.yaml` with `hermes config set` (so the admin's model choice is
kept; there is no template file to drift):
- `unauthorized_dm_behavior: decline` with a message pointing to `/feedback`, `/remind`, `/meal`.
- `hermes plugins enable seb` adds the plugin; `agent.disabled_toolsets` stays default (the owner's agent is
  the admin's own assistant).
`SOUL.md` describes the agent as the SelfEvaluationBot maintainer assistant. The profile `.env`
gets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS=<ADMIN_USER_ID>`, `ADMIN_USER_ID` and
`SEB_MAIN` copied from the main `.env` (setup never prints them).

### B4. The loop runs on Hermes cron
`hermes_profile/setup.sh cron` writes `$HERMES_HOME/scripts/seb-runner.sh`
(`BOT_PYTHON=<repo venv python> exec <MAIN>/runner/run.sh`, which keeps its lock and log) and
creates the job `seb-runner` (`every 1h`, `--no-agent`, `--deliver local`). The launchd runner
job is unloaded. The runner keeps sending its own Telegram messages; its buttons are handled by the
plugin (B2).

### B5. Merge in Hermes mode
`BOT_SERVICE` in `~/.seb-runner/config.env` (`launchd` default, `hermes`) and `HERMES_PROFILE`
(default `seb`). Hermes owns its Python environment (its package manager builds it from a lockfile
plus the `python_dependencies` of enabled plugins), so nothing is pip-installed into it by hand.
`hermes_profile/setup.sh` generates the copied plugin's `python_dependencies` from
`requirements.txt` with any `python-telegram-bot` line removed (Hermes pins its own PTB; the bot
code is compatible with both) and exact pins turned into minimums (`pkg==X` → `pkg>=X`): Hermes core
pins shared packages such as `python-dotenv` itself and refuses a plugin whose exact pin differs. In `hermes` mode, `merge_path`:
1. installs `requirements.txt` into the runner Python as today,
2. runs `hermes_profile/setup.sh sync` (re-copy the plugin with regenerated dependencies, then
   `hermes -p seb pm install`),
3. records the run as merged and notifies, and only then
4. starts `hermes -p <HERMES_GATEWAY_PROFILE, default> gateway restart` (the host gateway) in a
   detached session after a short delay — the tick
   itself runs inside that gateway's cron, so restarting earlier would kill the tick mid-merge.

### B6. Rollback
`hermes_profile/setup.sh uninstall` removes the cron job, disables the plugin, drops the bot token
from the `seb` profile and restarts the host gateway (which keeps serving the admin's other profiles);
`runner/setup.sh install-agents` brings back launchd `com.seb.bot` / `com.seb.runner`;
`BOT_SERVICE=launchd`.

## Risks / Trade-offs

- **PTB 20.7 vs 22.8.** The handlers use stable APIs (`CommandHandler`, `ConversationHandler`,
  `CallbackQueryHandler`, `ApplicationHandlerStop`). Tests keep running on 20.7; the plugin is
  smoke-tested by importing it with a fake context.
- **Hermes internals move fast.** Only documented plugin APIs are used; the session-identity import
  is guarded and fails closed (tools refuse).
- **One Telegram token, two senders.** The runner sends with the Bot API while the gateway polls;
  sending does not conflict with polling.
- **`/start` and `/help`** now show the bot's text, not Hermes's, for everyone including the owner.
