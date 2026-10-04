## Why

The autonomous runner only works on feedback the admin types. Problems the bot can see in its own
log go unnoticed until someone reads it: since 2026-09-29 the log holds four `Unhandled error`
entries — `BadRequest: Message to be replied not found` in `meal_picker` and `BadRequest: Query is
too old` in `runner_decision` — and nobody was told. This is "level 1 self-direction": the loop
points out work, and the admin decides whether it becomes work.

## What Changes

- On every hourly tick the trusted runner scans new lines of the bot log (`bot.err.log`) for
  **signals**, deterministically and without any agent or model:
  - `unhandled`: an `Unhandled error` entry, identified by exception class and the deepest
    in-repo frame (file + function). Suggested after 1 occurrence.
  - `reply_failed` / `reminder_failed`: `Reply not delivered…` / `Failed to deliver reminder…`
    lines. Suggested after 3 occurrences within 24 hours.
- Each new signal is sent to the admin as a 💡 Telegram message that states the **impact of the
  problem**, worked out deterministically: the user-facing feature (from the bot's own handler
  registrations, e.g. `meal_picker` → `/meal`), what the user experiences, how many distinct users
  were hit and how often, and — for known Telegram errors only — a plain-language cause. Buttons:
  **📋 Plan a fix** and **🙈 Dismiss**.
- The bot's error and reply-failure log lines gain the affected user / chat id, so the runner can
  count distinct users.
- **📋 Plan a fix** (admin only) stores an ordinary feedback submission from the admin, worded
  entirely by a template from the signal's facts, so the runner picks it up (📋 → ▶️ → 🔀 → ✅,
  see below). **🙈 Dismiss** snoozes that signal for 7 days.
- **Impact of the fix at PLAN time**: every PLAN output must include an `impact` block —
  `changes` (commands/files affected), `risk` (what could break) and `size` (small / medium /
  large) — shown in the 📋 message for all runs.
- **Build approval for runner-suggested work**: when a run comes from an accepted signal, the
  runner stops after PLAN and the 📋 message carries **▶️ Build** / **❌ Drop**. BUILD starts only
  after ▶️; ❌ follows the existing reject path. Runs from feedback the admin typed are unchanged.
- Suggestion text contains only facts the runner extracts under strict patterns (exception class,
  repo file, function name, counts, times) — never exception messages or any user-written text.
- At most one open suggestion per signal and at most 3 new suggestions per day.
- New table `runner_signals` in `sql/init.sql`; `auto_runs.decision` also allows `build`.

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

- **Code**: new `runner/signals.py` (log scan, fingerprints, thresholds, impact facts);
  `runner/runner.py` (scan each tick, build gate); `runner/validate.py` (PLAN `impact`);
  `runner/prompts/plan.md` (ask for `impact`); `runner/notify.py` (💡 message, impact in 📋,
  ▶️/❌ keyboard); `storage.py` (`runner_signals` methods, `build` decision); `bot.py` (`sig:`
  handler, `run:<id>:b` action, user/chat id in error and reply-failure log lines).
- **Schema**: `runner_signals` table (idempotent `CREATE TABLE IF NOT EXISTS`), and `build` added to the `auto_runs.decision` CHECK.
- **State file**: `~/.seb-runner/signals_offset` (log position).
- **Cost**: none per tick — no model calls. An accepted suggestion costs an ordinary run.
- **Out of scope**: auto-queuing without a tap (level 2), test failures on `main`, `runner.log`,
  `getUpdates` polling errors, and fixing the two bugs above (they become the first suggestions).
