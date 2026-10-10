## 1. Shared handlers (`bot.py`)

- [x] 1.1 Extract `register_handlers(application)` with the exact handlers and groups `main()` adds
- [x] 1.2 Extract `start_background(application)` (reminder loop on the running loop); `main()` uses both

## 2. Hermes plugin (`hermes_plugin/seb/`)

- [x] 2.1 `plugin.yaml` (tools, python_dependencies) and `register(ctx)`
- [x] 2.2 Locate `<MAIN>`, extend `sys.path`, load `<MAIN>/.env` without overriding
- [x] 2.3 Telegram factory: init DB, `register_handlers`, `start_background`; log and continue on failure
- [x] 2.4 Slash commands for the menu (`calc`, `meal` functional everywhere; others point to Telegram)
- [x] 2.5 Owner-only tools `seb_feedback_queue`, `seb_runner_status` with fail-closed identity check

## 3. Profile and setup (`hermes_profile/`)

- [x] 3.1 `hermes_profile/SOUL.md`; profile settings applied with `hermes config set`
- [x] 3.2 `hermes_profile/setup.sh install | cron | restart | uninstall`

## 4. Runner in Hermes mode

- [x] 4.1 `BOT_SERVICE`, `HERMES_PROFILE` in `runner/config.py`
- [x] 4.2 `merge_path`: `setup.sh sync` (plugin deps from requirements without PTB, `pm install`); detached gateway restart after merged + notified

## 5. Docs

- [x] 5.1 README: "Run the bot on Hermes" section (install, what changes for users, dashboard, rollback)

## 6. Tests (no Hermes, Telegram or network)

- [x] 6.1 `register_handlers` adds the same handlers/groups as before (fake application)
- [x] 6.2 Plugin `register(ctx)` with a fake ctx: registers the factory, commands and tools
- [x] 6.3 Telegram factory calls init + register + background; a raising init is logged, not raised
- [x] 6.4 Owner tools: admin allowed, other user refused, missing identity refused, CLI surface allowed
- [x] 6.5 Generated plugin dependencies drop `python-telegram-bot` only
- [x] 6.6 Hermes-mode merge restarts the gateway detached, after `merged`; launchd mode unchanged
