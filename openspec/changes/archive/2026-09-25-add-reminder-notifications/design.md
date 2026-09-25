## Context

The bot (`bot.py`) currently only reacts synchronously to incoming Telegram updates via `Application.run_polling()`; there is no existing background/scheduled execution path. Persistence conventions are established by `storage.py` (a static-method service class wrapping `psycopg` calls through `db.get_connection()`) and `sql/init.sql` (idempotent `CREATE TABLE IF NOT EXISTS` + `ALTER ... ADD CONSTRAINT` blocks). `requirements.txt` pins `python-telegram-bot==20.7` without the `[job-queue]` extra, so `Application`'s built-in `JobQueue` (which depends on APScheduler) is not available today.

The feedback that drove this change was clarified and answered "Option 1 and 2": the user wants both a one-off reminder for a specific time and a repeating notice on a schedule. "Tell me when my request ships" (option 3) was explicitly not chosen and is out of scope.

## Goals / Non-Goals

**Goals:**
- Let a user schedule a one-time reminder for a specific future time and receive it as a Telegram message when it's due.
- Let a user schedule a repeating notice on a fixed interval and keep receiving it each time it comes due, until cancelled.
- Let a user see and cancel their own pending reminders.
- Keep storage and delivery on the existing PostgreSQL + python-telegram-bot stack, following existing conventions (`storage.py`-style service, `sql/init.sql`-style schema, fail-fast startup validation).

**Non-Goals:**
- No notification for feedback/request status changes ("tell me when my request ships") — explicitly excluded by the user's answer.
- No natural-language time parsing beyond a small, well-defined set of formats (see Decisions) — full NLP date parsing is out of scope.
- No admin-facing reminder dashboard or cross-user visibility; a user can only see/cancel their own reminders.
- No new scheduler dependency (e.g. APScheduler/Celery); delivery uses a simple polling loop (see Decision below).
- No timezone-per-user configuration; all reminder times are interpreted and displayed in a single fixed timezone, Asia/Taipei (UTC+8), for every user in this first version (updated per admin note; internal storage stays UTC, see D5).

## Decisions

### D1: Delivery mechanism — in-process asyncio polling loop, not `JobQueue`/APScheduler
`python-telegram-bot`'s `JobQueue` requires the `job-queue` extra (APScheduler), which is not currently a dependency. Rather than adding a new scheduling library, delivery is implemented as a plain `asyncio` task (`reminders.delivery_loop(bot)`) started from `main()` (e.g. via the `Application`'s `post_init` hook or `asyncio.create_task` before `run_polling()`). The loop wakes on a fixed interval (proposed: every 30 seconds — frequent enough for "a specific time" reminders to feel timely, infrequent enough to keep DB load negligible), queries `reminders` for rows where `next_fire_at <= now()` and `active = true`, sends each via `bot.send_message(chat_id=..., text=...)`, and then either deactivates the row (one-time) or recomputes `next_fire_at` by adding the interval (repeating).
- **Alternative considered**: Add `python-telegram-bot[job-queue]`. Rejected for this first version to avoid a new dependency and keep the change small and easy to review; can be revisited if polling granularity becomes a real problem.
- **Alternative considered**: External cron/launchd job. Rejected because it would duplicate the runner's existing launchd patterns for a feature that's simple enough to run in-process, and would add operational complexity (a second process, its own restart/monitoring story) for no real benefit at this volume.

### D2: Storage — single `reminders` table covering both one-time and repeating notices
One table with an `is_recurring boolean` flag and a nullable `interval_seconds` column (or `interval` with unit), plus `next_fire_at timestamptz` (the one source of truth the delivery loop queries), `created_at`, `active boolean`, and `message_text`. One-time reminders have `is_recurring = false`, `interval_seconds = NULL`, and get `active = false` after their single delivery. Repeating notices have `is_recurring = true` and a positive `interval_seconds`; after each delivery `next_fire_at += interval_seconds` and the row stays `active`.
- **Alternative considered**: Two separate tables (`one_time_reminders`, `recurring_notices`). Rejected — the delivery loop, listing, and cancellation logic are identical modulo the recurrence math, so one table with a flag keeps the query surface and code simpler, matching the single-table-per-concept style already used elsewhere (e.g. `feedback_submissions`).

### D3: Command surface — `/remind` and `/reminders`
- `/remind <when> <message>` creates a reminder. `<when>` accepts either:
  - a relative offset: `in 10m`, `in 2h`, `in 3d` (one-time), or
  - a repeat spec: `every 1h`, `every 30m`, `every 1d` (repeating), or
  - an absolute time for the current day: `at 14:30` (one-time; if already past today, schedule for tomorrow).
  This mirrors the existing `/calc <expression>` style (single command, structured argument parsing, clear "Usage: ..." error message on bad input) documented in `openspec/specs/calculator/spec.md`.
- `/reminders` lists the user's active reminders with an id, next-fire time, recurrence indicator, and message text.
- `/reminders cancel <id>` deactivates a reminder the user owns; cancelling a reminder that doesn't belong to the user or doesn't exist returns a clear error, not a crash.
- **Alternative considered**: A conversation-style flow (like `/feedback`'s `ConversationHandler`) asking for time and message across turns. Rejected for v1 — a single-line command is faster for a reminder and avoids adding new conversation state; can be added later as a UX improvement if requested.

### D4: Parsing — small allowlisted grammar via `re`/`datetime`, no `eval`
Following the calculator's security precedent (AST-allowlist, no `eval`/`exec`), time parsing uses a small regex-based grammar (`in \d+[mhd]`, `every \d+[mhd]`, `at HH:MM`) with explicit validation and a `ValueError`-driven "Usage: ..." message on anything that doesn't match — no dynamic evaluation of user input.

### D5: Interpretation/display timezone: fixed Asia/Taipei (UTC+8)
Per admin direction, `at HH:MM` in `/remind` is interpreted as a wall-clock time in Asia/Taipei (not UTC, not host-local), converted to UTC for storage (`next_fire_at` stays TIMESTAMPTZ in UTC, storage contract unchanged). `/reminders` and the `/remind` confirmation message render `next_fire_at` converted back to Asia/Taipei for display, using the standard-library `zoneinfo.ZoneInfo("Asia/Taipei")`. This is a single fixed timezone for all users (no per-user setting), consistent with the existing non-goal on per-user timezone configuration.
- Alternative considered: keep `at HH:MM` and display in UTC (original design). Superseded by admin note: Asia/Taipei is clearer for the target user base.

### D6: Per-user active reminder cap: 20
To bound unbounded growth of a single users active reminders (and the resulting delivery-loop/list size), `ReminderService.create_reminder` counts the callers current active reminders and rejects creation once the caller already has 20 active reminders (one-time plus repeating combined), raising a dedicated `ReminderLimitExceededError`. `/remind` catches it and replies with a clear, distinct message (not the generic could-not-save failure).

### D7: Maximum offset/interval: 365 days
`in <n>m/h/d` and `every <n>m/h/d` both reject amounts whose total duration exceeds 365 days (31,536,000 seconds), with a clear error naming the limit. This bounds `next_fire_at`/`interval_seconds` to sane ranges. `at HH:MM` is unaffected since it always resolves to today or tomorrow.

## Risks / Trade-offs

- [Polling granularity means reminders can fire up to ~30s late] → Acceptable for "remind me" use cases; documented in the spec's scenarios as "delivered within the polling interval," not to-the-second precision.
- [Single fixed timezone may confuse users outside Asia/Taipei] to Documented explicitly as a non-goal/known limitation for this version; /remind help text and /help state times are interpreted and displayed in Asia/Taipei (UTC+8).
- [In-process polling loop dies silently if the bot process crashes] → It restarts with the bot process (same supervision as the rest of the bot, per `bot-supervision` capability); no additional recovery logic needed since `next_fire_at` is durable in PostgreSQL and survives restarts.
- [Repeating notices with a very short interval could spam a user or hammer the DB] → Mitigated by validating a minimum interval of 60 seconds (enforced in both `reminders.py` parsing and the `reminders` table CHECK constraint) at creation time, rejected with a clear error otherwise.

## Migration Plan

- Additive only: new table via `CREATE TABLE IF NOT EXISTS reminders` in `sql/init.sql` (idempotent, consistent with existing tables), new module, new handlers, new background task. No changes to existing tables or handlers.
- Rollback: revert the code change; the `reminders` table can remain in place unused (or be dropped manually) since nothing else depends on it.

## Open Questions

- Should repeating notices support recurrence beyond fixed intervals (e.g. "every day at 9am", cron-like) in a future iteration? Deferred — out of scope for this change; fixed-interval repetition satisfies "Option 2" as clarified.
