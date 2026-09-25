## 1. Schema

- [x] 1.1 Add `reminders` table to `sql/init.sql` (idempotent `CREATE TABLE IF NOT EXISTS`): `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`, `user_id BIGINT`, `chat_id BIGINT`, `message_text TEXT`, `is_recurring BOOLEAN`, `interval_seconds INT NULL`, `next_fire_at TIMESTAMPTZ`, `active BOOLEAN DEFAULT true`, `created_at TIMESTAMPTZ DEFAULT now()`
- [x] 1.2 Add an index on `(active, next_fire_at)` to support the delivery loop's poll query
- [x] 1.3 Add a CHECK constraint enforcing `interval_seconds IS NOT NULL` when `is_recurring = true` and `interval_seconds >= 60` (minimum recurring interval is 60 seconds, per design D1/Risks)
- [ ] 1.4 Run `sql/init.sql` twice locally to confirm it stays idempotent (not run: sandbox has no reachable Postgres, so this could not be executed against a live DB; the SQL itself uses the same `IF NOT EXISTS`/`DROP CONSTRAINT IF EXISTS` idempotent style as the rest of the file)

## 2. Parsing

- [x] 2.1 Implement `reminders.py` parsing helpers: `parse_relative("in 10m")`, `parse_absolute("at 14:30")`, `parse_interval("every 1h")` returning structured results or raising `ValueError` with a usage-style message (no `eval`)
- [x] 2.2 Unit tests for parsing: valid `in`/`at`/`every` forms (minutes/hours/days), invalid/garbage input, boundary cases (`at` time already passed today rolls to tomorrow), interval below minimum rejected

## 3. Storage service

- [x] 3.1 Implement `ReminderService` in `reminders.py` (or `storage.py`) following the `FeedbackService` static-method pattern: `create_reminder(user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds)`, `list_active(user_id)`, `cancel(user_id, reminder_id)`, `get_due(now)`, `mark_delivered(reminder_id)`, `reschedule(reminder_id, next_fire_at)`
- [x] 3.2 Unit/DB tests: create + list round-trip, cancel only affects the owning user's reminder, `get_due` returns only active rows with `next_fire_at <= now`, `reschedule` advances `next_fire_at` by the interval

## 4. Bot commands

- [x] 4.1 Add `/remind <when> <message>` `CommandHandler` in `bot.py` wired to the parsing + `ReminderService.create_reminder`, with "Usage: /remind ..." on missing/invalid input (mirrors `/calc` error style)
- [x] 4.2 Add `/reminders` `CommandHandler` listing the caller's active reminders (id, message, next-fire time, recurrence)
- [x] 4.3 Add `/reminders cancel <id>` handling (either a subcommand branch of the same handler or a dedicated handler) that only cancels reminders owned by the caller
- [x] 4.4 Register both commands with `application.add_handler(...)` and add them to the bot's command descriptions (`BotCommand` list / `/help` text), consistent with `command-hints`
- [x] 4.5 Handler tests with fakes: valid `/remind` creates and confirms, invalid `/remind` shows usage, `/reminders` lists correctly, `/reminders cancel` succeeds for owner and errors for non-owner/unknown id

## 5. Delivery loop

- [x] 5.1 Implement `reminders.delivery_loop(bot, poll_interval_seconds=30)`: on each tick, call `ReminderService.get_due(now)`, send each via `bot.send_message`, then `mark_delivered` (one-time) or `reschedule` (recurring); catch and log per-reminder send failures without stopping the loop
- [x] 5.2 Start the delivery loop from `main()` in `bot.py` via `Application.builder().post_init(...)` (the delivery loop task MUST be created with `asyncio.create_task` from inside the `post_init` coroutine, not synchronously before `run_polling()`, so it shares PTB's running event loop) so it runs alongside `run_polling()`
- [x] 5.3 Fail-fast startup check: verify the `reminders` table is reachable/queryable at startup, consistent with existing PostgreSQL startup validation
- [x] 5.4 Unit tests for the delivery loop: due one-time reminder is delivered once and deactivated, due recurring notice is delivered and its `next_fire_at` advances, a send failure for one reminder doesn't prevent delivery of the next due reminder in the same poll

## 6. Documentation

- [x] 6.1 Update `README.md` with `/remind` and `/reminders` usage examples and the accepted time formats
- [x] 6.2 Document the fixed-timezone assumption and minimum recurring interval in the command's `/help` text or usage message

## 7. Verification

- [x] 7.1 Run the full existing test suite to confirm no regressions
- [ ] 7.2 Manual end-to-end check: schedule a short one-time reminder (`in 1m`), confirm delivery and that it does not fire again (not run: sandbox has no live Telegram bot or reachable DB to exercise this against)
- [ ] 7.3 Manual end-to-end check: schedule a short repeating notice (`every 1m`), confirm it fires more than once, then cancel it via `/reminders cancel <id>` and confirm it stops firing (not run: sandbox has no live Telegram bot or reachable DB to exercise this against)
