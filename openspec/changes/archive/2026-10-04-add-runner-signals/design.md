## Context

The runner (`runner/runner.py`) is started hourly by launchd. `tick()` resumes an in-flight run,
or — if not throttled — starts work on the oldest actionable **admin** submission. The bot runs
under launchd and logs to `~/.seb-runner/logs/bot.err.log`.

That text log cannot be a trusted input: Python `logging` writes newlines unescaped, and user
influenced text reaches it (database error details in `storage.py`, reminder delivery errors in
`reminders.py`, exception messages after every traceback). A message containing
`\n<timestamp> - __main__ - ERROR - Unhandled error\nTraceback…\n  File "<MAIN>/bot.py", line 1, in
some_words` is indistinguishable from a real record (reproduced during evaluation). Character
patterns limit *which characters* pass, not *what they say*. So signals come from a separate,
structured event stream the bot writes from exception objects, never from log text.

The runner's trust model: only admin-written feedback starts work, agents run sandboxed (the
sandbox denies `~/.seb-runner`), and the trusted runner never executes agent-controlled content.

## Goals / Non-Goals

**Goals:**
- Surface recurring or unexpected problems to the admin, with no model cost.
- State the impact of the problem in the suggestion, and the impact of the fix before building.
- Turn a suggestion into work only through explicit admin taps (📋, then ▶️).
- No user-controlled text can reach a suggestion, a submission, or an agent prompt.

**Non-Goals:**
- Starting work without a tap (level 2), or merging without ✅ (level 3).
- Signals from test runs, `runner.log`, metrics, or `getUpdates` polling errors.
- Diagnosing the cause — that is the PLAN agent's job once a submission exists.

## Decisions

### D1. Deterministic, no model
Detection, impact and wording are code in the trusted runner. No agent sees the events, and a tick
costs nothing. *Alternative*: a model summarising the log — rejected (cost, and it would put
user-influenced text in front of a model).

### D2. Structured event file written by the bot
New module `signals_events.py` (repo root, imported by `bot.py` and `reminders.py`) appends one
JSON object per line to the file named by env `SEB_SIGNALS_FILE`. **There is no default: when the
variable is unset, nothing is written.** It is set only in the bot's launchd plist
(`runner/launchd/com.seb.bot.plist.template` → `{{HOME}}/.seb-runner/logs/signals.jsonl`), so test
runs — developer `pytest`, the sandboxed verification, and `testdb.run_full_suite` after ✅, which
runs outside the sandbox with the real `HOME` — never write events. Every field is computed from
objects, never from message text:

```json
{"v": 1, "ts": "2026-10-04T03:44:10.123+00:00", "kind": "unhandled",
 "exc": "telegram.error.BadRequest", "file": "bot.py", "func": "meal_picker", "line": 249,
 "user": 908274693, "known_cause": "reply_target_gone"}
```

- `kind`: `unhandled` (from `bot._on_error`, for errors that are not `_retryable` network errors),
  `reply_failed` (from `bot._reply` when it gives up), `reminder_failed` (from
  `reminders._deliver_due` when a send fails).
- `exc`: `f"{type(e).__module__}.{type(e).__qualname__}"` (`builtins.` dropped).
- `file` / `func` / `line`: the deepest frame of `traceback.extract_tb(e.__traceback__)` whose path
  is inside the repository root — `Path(signals_events.__file__).resolve().parent`, never the
  current directory — and not under any `site-packages` or `tests/`; `file` is relative to the
  root.
  For `reply_failed` the frame is the caller of `_reply` (`sys._getframe(1)`), e.g.
  `feedback_bug`. Omitted when no in-repo frame exists.
- `user`: `update.effective_user.id` for `unhandled`; `message.chat_id` for `reply_failed`; the
  reminder's `user_id` for `reminder_failed`. Integers only; omitted when unknown.
- `known_cause`: computed **in the bot** by exact match of `(exc, str(e))` against
  `KNOWN_CAUSES` in `signals_events.py`; only the key is written (D9). The message itself is never
  written.
- `json.dumps` escapes newlines, so one event is always one line. Writing is best-effort:
  any `OSError` (missing directory, sandboxed test runs) is swallowed and never affects the bot.
- Polling errors (`_retryable` network errors in `_on_error`) are not written.

### D3. Runner-side validation (defence in depth)
`runner/signals.py` accepts an event only if all of these hold, and drops it otherwise (counted):
- valid JSON object with `v == 1` and `kind` in the three kinds;
- `ts` parses as an ISO timestamp **with** an offset and is not in the future (+5 min slack);
- `exc` matches `^[A-Za-z_][\w.]{0,100}$`;
- if present: `file` is a path tracked by git on `main` in `<MAIN>` (`git ls-tree --name-only
  main -- <file>`), not under `site-packages` or `tests/`; `func` matches `^\w{1,100}$` **and** `def <func>(` / `async def <func>(` occurs in
  that file on `main` (`git show main:<file>`); `line` is a positive int; `user` is an int ≥ 0;
- `known_cause`, if present, is a key of `KNOWN_CAUSES`.
Fingerprints: `unhandled:<exc>:<file>:<func>`, `reply_failed:<exc>:<func>`, `reminder_failed:<exc>`.
The line number is an informational hint only, never part of the fingerprint.

### D4. Incremental reading with an exact cursor
- The cursor (`inode`, `offset`) lives in a single-row table `runner_signal_cursor` and is updated
  **in the same transaction** as the occurrences it covers — a crash can neither lose nor
  double-count events.
- Each tick reads from `offset`, at most 5 MB, and processes only up to the last `\n` in what it
  read (a partial final line waits). If the inode changed or the file is shorter than `offset`
  (rotation, truncation), it reads from 0.
- With no cursor row (first run), the cursor is created at the file's current end: nothing is
  replayed. With no file, nothing happens.

### D5. Tables
```sql
CREATE TABLE IF NOT EXISTS runner_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint VARCHAR(300) NOT NULL UNIQUE,
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('unhandled', 'reply_failed', 'reminder_failed')),
    exc VARCHAR(101) NOT NULL,
    file VARCHAR(200),
    func VARCHAR(100),
    last_line INT,
    known_cause VARCHAR(50),
    occurrences INT NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    recent JSONB NOT NULL DEFAULT '[]',   -- occurrence timestamps within the last 24 h
    users JSONB NOT NULL DEFAULT '[]',    -- distinct ids (integers)
    status VARCHAR(20) NOT NULL DEFAULT 'observed'
        CHECK (status IN ('observed', 'suggested', 'accepted', 'dismissed')),
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary TEXT,                         -- rendered 💡 text (D9), set when suggested
    suggested_at TIMESTAMPTZ,             -- for the 3-per-24 h cap
    message_id BIGINT,
    feedback_submission_id UUID REFERENCES feedback_submissions(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS runner_signal_cursor (
    id BOOLEAN PRIMARY KEY DEFAULT true CHECK (id),
    inode BIGINT NOT NULL,
    byte_offset BIGINT NOT NULL
);
ALTER TABLE auto_runs ADD COLUMN IF NOT EXISTS plan_summary TEXT;
ALTER TABLE auto_runs ADD COLUMN IF NOT EXISTS plan_message_id BIGINT;
-- decision gains 'build' (drop + re-add, as init.sql already does for other constraints)
```
The 💡 text is rendered by the runner from the validated columns (D9) when the signal is suggested and stored in `summary`, so the bot's 📋 handler reuses it without the runner's handler map.

### D6. Suggestion lifecycle
```
observed ──threshold met──▶ suggested ──📋──▶ accepted ──submission resolved──▶ observed (counters reset)
    ▲                          │                  └────submission wont_do──────▶ dismissed
    └── 7 days + new occurrences ── dismissed ◀──🙈──┘
```
- Thresholds: `unhandled` 1 occurrence; `reply_failed` / `reminder_failed` 3 within 24 h.
- Suggested when the threshold is met and status is `observed`, or `dismissed` for ≥ 7 days with
  occurrences after `status_changed_at`.
- Each tick, accepted signals whose submission has a `resolved` event return to `observed`
  (counters reset — a regression is suggested again); those with a `wont_do` event (❌ at PLAN or
  🔀) become `dismissed`. Detected by joining `feedback_events` on `feedback_submission_id`.
- At most 3 suggestions per rolling 24 h, oldest `first_seen` first. A failed send leaves the
  status unchanged, so it is retried next tick.

### D7. Where it runs in `tick()`
First in every tick, before resuming or throttling: read → record (one transaction, with the
cursor) → reset/dismiss accepted signals → send suggestions. Wrapped so any exception is logged
and never stops the rest of the tick. It does not count against the throttle. One summary line
per tick in the runner log (events read / dropped / suggestions sent).

### D8. Telegram: 💡 message and `sig:` callback
`notify.signal(signal)` sends (plain text, rendered from D9):
```
💡 /meal sometimes fails for users
Impact: the user sends /meal and probably gets no reply
Who:    1 user · 2 times · last 2026-09-29 06:29 · none in the last 24 h
Cause:  the user's message was gone before the bot replied
Where:  bot.py → meal_picker (line 249)
[📋 Plan a fix]  [🙈 Dismiss]
```
Callback `sig:<uuid>:p|d`, handled by `bot.signal_decision`: admin only (others ignored),
`query.answer()` first, then:
- `p`: `FeedbackService.accept_signal(id, admin_id)` — **one transaction**: `UPDATE runner_signals
  SET status='accepted' … WHERE id=%s AND status='suggested' RETURNING …`; if a row came back,
  insert the submission (bug text = rendered summary, suggestion text = "Find the cause and fix it
  so this no longer happens. (Suggested by the runner, signal <fingerprint>.)"), the `submitted`
  event, and the link. It does not reuse `store_submission` (separate connection, swallows
  errors). A double tap gets no row back → "Already handled".
- `d`: `dismiss_signal` (`WHERE status='suggested'`), message edited to "🙈 Dismissed for 7 days".

### D9. Rendering the impact (problem)
- **Feature** — from `<MAIN>/bot.py` on `main` (`git show main:bot.py`):
  `CommandHandler("<cmd>", <func>)` → `/<cmd>`; functions listed inside a `ConversationHandler(…)`
  (entry points and states) → that conversation's entry command (`feedback_bug` → `/feedback`);
  `CallbackQueryHandler(<func>, pattern=r"^<prefix>:")` → a fixed label per prefix (`run:` →
  "the buttons on runner messages", `apv:` / `clr:` → "the clarification buttons", `sig:` → "the
  💡 suggestion buttons"); `file == "reminders.py"` → "reminder delivery"; otherwise
  "internal code (`<func>`)".
- **Experience** — fixed text per kind and feature type: command → "the user sends /x and
  probably gets no reply"; button → "the tap probably shows no result"; `reply_failed` → "a reply
  did not arrive (what the user typed is still saved)"; `reminder_failed` → "a reminder is delayed
  until a retry succeeds".
- **Who / how often** — distinct `users` ("users unknown" if none), `occurrences`, `last_seen`
  (shown in Asia/Taipei like the rest of the bot), count in the last 24 h.
- **Cause** — `KNOWN_CAUSES[known_cause].explanation`, e.g. `reply_target_gone` (`BadRequest`,
  "Message to be replied not found") → "the user's message was gone before the bot replied";
  `query_too_old` → "the button was answered too late (e.g. during a bot restart)";
  `bot_blocked` (`Forbidden`, "Forbidden: bot was blocked by the user") → "the user has blocked
  the bot"; `timed_out` (`TimedOut`, "Timed out") → "Telegram did not answer in time". Omitted
  when there is no key.

### D10. Trust boundary
Every character of a 💡 message or an accepted submission comes from (a) fixed template text,
(b) `KNOWN_CAUSES` text, or (c) validated columns that were computed by the bot from exception
objects and code locations, then re-checked against `main` (D3). No message text, log text or
user input is read by the runner. The submission is authored by the admin's tap, so "only admin
feedback triggers runs" still holds.

### D11. Impact of the fix in PLAN output
`runner/prompts/plan.md` asks for:
```json
{"stage": "planned", "change_name": "…", "summary": "…",
 "impact": {"changes": "<commands/files affected>", "risk": "<what could break>", "size": "small|medium|large"}}
```
`validate.validate_plan` requires `impact` (`size` in the three values; `changes` / `risk`
non-empty strings ≤ 300 characters); missing or invalid fails PLAN. The runner stores the summary
and impact together in `auto_runs.plan_summary`
as JSON (`{"summary": …, "impact": {…}}`), so a resent 📋 shows both. `notify.planned` shows them for every run:
```
Changes: …
Risk:    …
Size:    small
```

### D12. Build approval for runner-suggested work
A run is **gated** when its submission is linked from `runner_signals.feedback_submission_id`.
- `do_plan`, gated: store `plan_summary`, set stage `planned`, send 📋 with "Waiting for your
  decision — no other work starts until then" and **▶️ Build** / **❌ Drop** (`run:<id>:b` /
  `run:<id>:r`), store `plan_message_id`. Non-gated: unchanged text ("Building now…"), continue.
- `handle_inflight`, stage `planned`, gated:
  - `plan_message_id` is NULL (send failed or crash before it) → resend from `plan_summary`;
  - `decision='build'` → BUILD; `decision='reject'` → existing reject path; otherwise `waiting`.
  Non-gated `planned` → BUILD (unchanged crash resume).
- `do_build` clears `decision` as it starts, so no stale decision survives into
  `awaiting_decision`. `decision_note` is kept, as today, so build retries still see the 💬 note.
- `set_auto_run_decision` applies only these pairs (one SQL `WHERE`):
  `stage IN ('awaiting_decision','failed') AND decision IN ('merge','reject','changes')`, or
  `stage='planned' AND decision IN ('build','reject') AND` the run is gated (`EXISTS` on
  `runner_signals`). `merge` is never accepted in `planned`.
- A gated run whose PLAN fails behaves as today (⚠️, 💬 re-plans, and it stops at `planned` again).
- `runner_decision` in `bot.py` maps `b` → `build` ("the build starts within an hour").

*Alternative*: gate every run — rejected for now; feedback the admin typed already had a human
decide the goal.

## Risks / Trade-offs

- [Plist not re-rendered after merge] → `SEB_SIGNALS_FILE` is unset, so no events and no
  signals, silently. The migration step says so; the runner logs "no events file" each tick.
- [Events file not writable] → No signals; the bot is unaffected. The runner logs "no events
  file" once per tick at debug level.
- [Noisy signals] → Thresholds, one open suggestion per fingerprint, 3 per day, 7-day snooze.
- [Same exception class twice in one function for different reasons] → One signal. The PLAN agent
  investigates the function.
- [No replay of past errors] → The two existing bugs are suggested when they next occur.
- [A gated run blocks the queue until decided] → Said in the 📋 message; lost messages are resent.
- [Handler map misses a registration style] → Falls back to "internal code (`<func>`)"; tests pin
  the current `bot.py`.
- [PLAN agent's impact is an estimate] → The 🔀 diff and sensitive-path list remain the ground
  truth before ✅.

## Migration Plan

Schema changes are idempotent and run at bot start (`db.init_database`). Merge, then re-render
and reload the launchd agents (`runner/setup.sh install-agents`) so the bot gets
`SEB_SIGNALS_FILE` and starts writing `signals.jsonl`; the next tick creates the cursor at the
file's end. Rollback:
revert the merge; the unused tables, columns and file are harmless.
