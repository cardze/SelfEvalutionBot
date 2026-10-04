## Why

The autonomous runner only works on feedback the admin types. Problems the bot can see in its own
log go unnoticed until someone reads it: since 2026-09-29 the log holds four `Unhandled error`
entries — `BadRequest: Message to be replied not found` in `meal_picker` and `BadRequest: Query is
too old` in `runner_decision` — and nobody was told. This is "level 1 self-direction": the loop
points out work, and the admin decides whether it becomes work.

## What Changes

- The bot writes a **structured event file** (`signals.jsonl`, one JSON object per line) when a
  handler hits an unhandled error, a reply gives up, or a reminder send fails. Every field is
  computed from the exception object and code location (exception class, repo file, function,
  line, user/chat id, known-cause key) — never from message or log text, so user-influenced text
  cannot forge or shape an event. (Parsing the text log was rejected: newlines in logged user text
  can forge whole records.)
- On every hourly tick the trusted runner reads new events, deterministically and without any
  agent or model, re-validates them against `main` (file tracked by git, function defined there),
  and keeps an exact cursor in the database. Thresholds: an unhandled error after 1 occurrence;
  failed replies / reminders after 3 within 24 hours.
- Each new signal is sent to the admin as a 💡 Telegram message that states the **impact of the
  problem**, worked out deterministically: the user-facing feature (from the bot's own handler
  registrations, e.g. `meal_picker` → `/meal`), what the user experiences, how many distinct users
  were hit and how often, and — for known Telegram errors only — a plain-language cause. Buttons:
  **📋 Plan a fix** and **🙈 Dismiss**.
- **📋 Plan a fix** (admin only) stores an ordinary feedback submission from the admin, worded
  entirely by a template from the signal's facts, so the runner picks it up (📋 → ▶️ → 🔀 → ✅,
  see below). **🙈 Dismiss** snoozes that signal for 7 days.
- **Impact of the fix at PLAN time**: every PLAN output must include an `impact` block —
  `changes` (commands/files affected), `risk` (what could break) and `size` (small / medium /
  large) — shown in the 📋 message for all runs.
- **Build approval for runner-suggested work**: when a run comes from an accepted signal, the
  runner stops after PLAN and the 📋 message carries **▶️ Build** / **❌ Drop**. BUILD starts only
  after ▶️; ❌ follows the existing reject path. Runs from feedback the admin typed are unchanged.
- Suggestion text contains only fixed template text, fixed known-cause explanations and validated
  event fields — never exception messages, log text or anything a user wrote.
- At most one open suggestion per signal and at most 3 new suggestions per day.
- New tables `runner_signals` and `runner_signal_cursor`; `auto_runs` gains `plan_summary`,
  `plan_message_id`, and `build` as a decision.

## Capabilities

### New Capabilities
- `runner-signals`: detecting signals in the bot log, suggesting them to the admin, and turning
  an accepted suggestion into an admin feedback submission.

### Modified Capabilities
- `autonomous-feedback-runner`: **Stage progression within a run** — PLAN output includes an
  impact block shown in 📋, and runs from accepted signals pause after PLAN for ▶️ / ❌.
  **Admin decisions via Telegram** — adds the ▶️ Build tap. "Only admin feedback triggers runs"
  still holds: a suggestion becomes work only as a submission created by the admin's own tap.

## Impact

- **Code**: new `signals_events.py` (event writer + known causes, used by the bot);
  new `runner/signals.py` (event reader, validation, fingerprints, thresholds, impact);
  `runner/runner.py` (scan each tick, build gate); `runner/validate.py` (PLAN `impact`);
  `runner/prompts/plan.md` (ask for `impact`); `runner/notify.py` (💡 message, impact in 📋,
  ▶️/❌ keyboard); `storage.py` (`runner_signals` methods, `build` decision); `bot.py` (`sig:`
  handler, `run:<id>:b` action, events from `_on_error` / `_reply`); `reminders.py` (event on a
  failed send).
- **Schema** (idempotent): `runner_signals`, `runner_signal_cursor`, two `auto_runs` columns, and
  `build` in the `auto_runs.decision` CHECK.
- **Files**: `~/.seb-runner/logs/signals.jsonl` (written by the bot, read by the runner).
- **Cost**: none per tick — no model calls. An accepted suggestion costs an ordinary run.
- **Out of scope**: auto-queuing without a tap (level 2), test failures on `main`, `runner.log`,
  `getUpdates` polling errors, and fixing the two bugs above (they become the first suggestions).
