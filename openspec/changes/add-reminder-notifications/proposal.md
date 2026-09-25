## Why

A user asked for "a notice function" and, when clarified, confirmed they want both a one-time reminder they can set for a specific time and a notice that repeats on a schedule ("Option 1 and 2"). The bot today has no way to notify a user later — every interaction is synchronous (calculator, feedback) and nothing survives past the current chat turn. Users have no way to ask the bot to follow up with them at a future point in time.

## What Changes

- Add a new `/remind` command that lets a user create a one-time reminder ("remind me about X at/in Y") and a repeating notice ("remind me about X every Y").
- Add a new `/reminders` command to list a user's upcoming reminders (one-time and repeating) and a way to cancel one (e.g. `/reminders cancel <id>`).
- Add a `reminders` table in PostgreSQL to persist reminder text, owner, due time, and (for repeating notices) an interval/recurrence rule and next-fire time.
- Add a background delivery loop that periodically polls PostgreSQL for due reminders and sends a Telegram message to the owning user via the bot, then either marks the reminder delivered (one-time) or advances it to its next occurrence (repeating).
- Add startup wiring so the delivery loop starts alongside the existing bot polling loop and fails fast if it cannot read the reminders table.

## Capabilities

### New Capabilities
- `reminder-notifications`: Lets a Telegram user schedule a one-time reminder for a specific time or a repeating notice on an interval, and receive it as a bot message when it comes due; includes listing and cancelling reminders.

### Modified Capabilities
<!-- No existing capability's requirements change; this is purely additive. -->

## Impact

- **Code**: New `reminders.py` (parsing + service layer, following the `storage.py` / `FeedbackService` pattern), new handlers wired into `bot.py` (`/remind`, `/reminders`), a new background polling task started from `main()`.
- **APIs**: New user-facing commands `/remind` and `/reminders`; no external APIs beyond the existing Telegram Bot API (`bot.send_message`).
- **Dependencies**: None expected beyond what's already installed (`python-telegram-bot`, `psycopg`); no new third-party scheduler library — see design.md for the polling-loop decision.
- **Systems**: New `reminders` table in the existing PostgreSQL database (`sql/init.sql`), created idempotently like existing tables.
- **Data lifecycle**: Reminder rows persist until cancelled by the user or, for one-time reminders, marked delivered; repeating notices persist indefinitely until cancelled and keep advancing to their next occurrence.
- **Scope boundary (explicit assumption)**: This change covers only reminders/notices the user schedules themselves. It explicitly excludes "tell me when my request ships" (the third clarification option, not selected) and any other event-triggered or feedback-status notifications — those are out of scope for this change.
