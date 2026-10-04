## Context

The runner (`runner/runner.py`) is started hourly by launchd. `tick()` resumes an in-flight run,
or — if not throttled — starts work on the oldest actionable **admin** submission. The bot runs
under launchd too and writes its log to `~/.seb-runner/logs/bot.err.log` (python `logging`, one
header line per record, tracebacks on following lines). Since `harden-feedback-conversation` the
bot logs:

```
… - __main__ - ERROR - Unhandled error
Traceback (most recent call last):
  File "/…/SelfEvalutionBot/bot.py", line 249, in meal_picker
  …
telegram.error.BadRequest: Message to be replied not found
… - __main__ - WARNING - Reply not delivered after 3 attempt(s): TimedOut: Timed out
… - reminders - ERROR - Failed to deliver reminder <uuid>: <error>
… - __main__ - WARNING - Telegram network error: NetworkError: Bad Gateway   (polling noise)
```

The runner's trust model: only admin-written feedback starts work, agents run sandboxed, and the
trusted runner never executes agent-controlled content.

## Goals / Non-Goals

**Goals:**
- Surface recurring or unexpected problems from the bot log to the admin, with no model cost.
- Turn a suggestion into work only through an explicit admin tap.
- Keep every word an agent later reads either admin-written or runner-templated from
  strictly-validated facts.

**Non-Goals:**
- Starting work without a tap (level 2), or merging without ✅ (level 3).
- Signals from test runs, `runner.log`, metrics, or `getUpdates` polling errors.
- Diagnosing the cause — that is the PLAN agent's job once a submission exists.

## Decisions

### D1. Deterministic detection in the trusted runner, no model
`runner/signals.py` parses the log with regular expressions. No agent sees the log (the sandbox
already denies `~/.seb-runner`), and a tick costs nothing. *Alternative*: a cheap model summarising
the log — rejected: it would put raw log text (which can carry user-influenced content) in front of
a model, and costs money every hour.

### D2. Incremental reading
The runner keeps `~/.seb-runner/signals_offset` = `{"inode": …, "offset": …}`. Each tick reads from
the offset to EOF. If the inode changed or the file is shorter than the offset (rotation or
truncation), it starts from 0. On first run (no state file) it starts from **the current end** —
historical errors are not replayed. Reads at most 5 MB per tick. A partial last line (no trailing
newline) is left for the next tick.

### D3. Signals and fingerprints (facts only)
| Kind | Matched by | Fingerprint | Threshold |
|---|---|---|---|
| `unhandled` | header `… - ERROR - Unhandled error`, then the traceback until the next header | `unhandled:<exception class>:<file>:<function>` | 1 occurrence |
| `reply_failed` | `… - WARNING - Reply not delivered after N attempt(s): <ErrorClass>:` | `reply_failed:<ErrorClass>` | 3 within 24 h |
| `reminder_failed` | `… - ERROR - Failed to deliver reminder <uuid>: …` | `reminder_failed` | 3 within 24 h |

- `<exception class>` must match `^[A-Za-z_][\w.]{0,100}$` (the token before the first `:` on the
  last traceback line); `<file>` is the deepest `File "<MAIN>/<path>"` frame inside the main
  checkout, with `<path>` matching `^[\w./-]{1,200}$`; `<function>` must match `^\w{1,100}$`.
  Anything that fails validation is dropped (counted in the runner log, never suggested).
- Exception messages, reminder ids/texts and every other part of the line are discarded. Line
  numbers are kept only as an informational hint in the 💡 message, not in the fingerprint, so an
  edit to the file does not create a new signal. The one exception is D9's known-cause lookup,
  which compares the message for **exact equality** against a fixed table and then discards it.
- A `user=<digits>` / `chat=<digits>` token (D10) is kept only if it matches `^\d{1,20}$`.
- `Telegram network error` lines (polling) are ignored.

### D4. Table `runner_signals`
```sql
CREATE TABLE IF NOT EXISTS runner_signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fingerprint VARCHAR(300) NOT NULL UNIQUE,
    kind VARCHAR(30) NOT NULL CHECK (kind IN ('unhandled', 'reply_failed', 'reminder_failed')),
    summary TEXT NOT NULL,                -- templated from validated facts only
    occurrences INT NOT NULL DEFAULT 0,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL,
    recent JSONB NOT NULL DEFAULT '[]',   -- timestamps within the 24 h window
    users JSONB NOT NULL DEFAULT '[]',    -- distinct user/chat ids seen (digits only)
    impact TEXT NOT NULL DEFAULT '',      -- D9 impact lines, templated
    known_cause VARCHAR(50),              -- key into D9's known-cause table, or NULL
    status VARCHAR(20) NOT NULL DEFAULT 'observed'
        CHECK (status IN ('observed', 'suggested', 'accepted', 'dismissed')),
    status_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    message_id BIGINT,
    feedback_submission_id UUID REFERENCES feedback_submissions(id) ON DELETE SET NULL
);
```
New `FeedbackService` methods: `record_signal_occurrences`, `signals_to_suggest`,
`mark_signal_suggested`, `accept_signal`, `dismiss_signal`.

### D5. Suggestion lifecycle
```
observed ──threshold met──▶ suggested ──📋──▶ accepted ──submission resolved──▶ observed
    ▲                          │                                       (count resets)
    └──── 7 days + new occurrences ── dismissed ◀──🙈──┘
```
- A signal is suggested when its threshold is met and its status is `observed`, or it is
  `dismissed` for ≥ 7 days **and** has new occurrences since the dismissal.
- `accepted` is not re-suggested while its submission is unresolved; once resolved it returns to
  `observed` with its counters reset, so a regression after the fix is suggested again.
- At most 3 suggestions per rolling 24 h; the rest wait for a later tick (oldest `first_seen`
  first).

### D6. Where it runs in `tick()`
Signal scanning runs first in every tick, before resuming or throttling, wrapped so that any
exception is logged and never prevents the rest of the tick. It does not count against the 5-hour
throttle. An accepted suggestion becomes an ordinary admin submission and waits in the normal
queue.

### D7. 💡 message and callback
`notify.signal(signal)` sends (plain text, built from D9's facts):
```
💡 /meal sometimes fails for users
Impact: the user sends /meal and probably gets no reply
Who:    1 user · 2 times · last 2026-09-29 06:29 · none in the last 24 h
Cause:  the user's message was gone before the bot replied (Telegram: message not found)
Where:  bot.py → meal_picker (line 249)
[📋 Plan a fix]  [🙈 Dismiss]
```
The `Cause:` line appears only for a known cause; `Who:` says "users: unknown" when no ids were
logged (e.g. reminders).
Callback data `sig:<uuid>:p` / `sig:<uuid>:d`, handled in `bot.py` by `signal_decision`
(admin-only, ignored otherwise, like `runner_decision`). It calls `query.answer()` first, then:
- `p`: `accept_signal` stores a submission for the admin — `bug_text` = the summary,
  `suggestion_text` = "Find the cause and fix it so this no longer happens. (Suggested by the
  runner from the bot log, signal <fingerprint>.)" — records `submitted`, links it, and edits the
  message to "📋 Queued as feedback".
- `d`: `dismiss_signal`, edits the message to "🙈 Dismissed for 7 days".
- Already-decided signals answer "Already handled" and change nothing.

### D8. Trust boundary
Every character an agent can later read from an accepted suggestion comes from (a) the runner's
fixed template or (b) fields that passed D3's strict patterns. User text in the log (e.g. inside
an exception message) is never extracted. The submission is authored by the admin's tap, so the
existing "only admin feedback triggers runs" requirement still holds unchanged.

### D9. Problem impact, deterministic
Built by the trusted runner from the main checkout and the validated facts — no model:
- **Feature**: the runner reads `<MAIN>/bot.py` and matches `CommandHandler("<cmd>", <func>)` →
  "`/<cmd>`" and `CallbackQueryHandler(<func>, pattern=r"^<prefix>:")` → a fixed label per prefix
  (`run:` → "the ✅/❌/💬 buttons on runner messages", `apv:` / `clr:` → "the clarification
  buttons", `sig:` → "the 💡 suggestion buttons"). Functions in `reminders.py` → "reminder
  delivery". Anything else → "internal code (`<function>`)". The feature name is used in the
  headline ("/meal sometimes fails for users").
- **Experience**, fixed text per kind: `unhandled` in a command or button handler → "the user
  sends /x and probably gets no reply" / "the tap probably shows no result"; `reply_failed` → "a
  /feedback reply did not arrive (what the user typed is still saved)"; `reminder_failed` → "a
  reminder is delayed until a retry succeeds".
- **Who / how often**: distinct ids from `users`, total occurrences, last seen, count in the last
  24 h.
- **Known cause**: a fixed table keyed by (exception class, exact message), e.g.
  `(telegram.error.BadRequest, "Message to be replied not found")` → "the user's message was gone
  before the bot replied"; `(…BadRequest, "Query is too old and response timeout expired or query
  id is invalid")` → "the button was answered too late (e.g. during a bot restart)";
  `(telegram.error.Forbidden, "Forbidden: bot was blocked by the user")` → "the user has blocked
  the bot"; `(telegram.error.TimedOut, "Timed out")` → "Telegram did not answer in time". Only the
  table's own explanation text is ever output.

The handler map reads trusted, already-merged code in `<MAIN>`; it never reads a workspace.

### D10. User ids in bot log lines
`bot._on_error` appends ` user=<id>` when `update` has an `effective_user`; `_reply` appends
` chat=<id>` from `message.chat_id` when present. Ids are Telegram numeric ids already stored in the
database, so no new personal data is created; only digit strings are extracted (D3).

### D11. Impact of the fix in PLAN output
`runner/prompts/plan.md` asks for:
```json
{"stage": "planned", "change_name": "…", "summary": "…",
 "impact": {"changes": "<commands/files affected>", "risk": "<what could break>", "size": "small|medium|large"}}
```
`validate.validate_plan` requires `impact`, with `size` in the three values and `changes` / `risk`
non-empty strings capped at 300 characters each; a missing or invalid block fails PLAN like any
other output error. `notify.planned` adds:
```
Changes: …
Risk:    …
Size:    small
```
This applies to every run, not only signal-originated ones.

### D12. Build approval for runner-suggested work
A run is **gated** when its submission is linked from `runner_signals.feedback_submission_id`
(a persistent fact, so crash recovery cannot bypass it).
- `do_plan` for a gated run stops at stage `planned` and sends 📋 with **▶️ Build** /
  **❌ Drop** (callback `run:<id>:b` / `run:<id>:r`). Non-gated runs continue to BUILD as today.
- `handle_inflight`, stage `planned`: gated and `decision='build'` → clear the decision and run
  BUILD; gated and `decision='reject'` → existing reject path (records `wont_do`, archives the
  proposal with `REJECTED.md`); gated and no decision → `waiting`. Non-gated → BUILD (unchanged
  crash resume).
- `auto_runs.decision` CHECK gains `build` (drop + re-add the constraint, as `init.sql` already
  does for other constraints). `set_auto_run_decision` accepts `build` only in stage `planned`, and
  `reject` additionally in stage `planned`.
- Waiting costs nothing: no agent runs until ▶️. The single-in-flight rule still holds, so a
  pending gated run blocks new work until decided — the 📋 message says so.

*Alternative*: gate every run — rejected for now; runs from feedback the admin wrote have already
had a human decide the goal.

## Risks / Trade-offs

- [Log format changes break matching] → Signals silently stop. Mitigation: parser unit tests use
  the exact current format; the runner logs a per-tick count of matched / dropped records.
- [Noisy signals] → Thresholds, one open suggestion per fingerprint, 3 per day, 7-day snooze.
- [Two different bugs in the same function with the same exception class] → Merge into one
  signal. Acceptable: the PLAN agent investigates the function.
- [Startup offset skips the two existing bugs] → Intended (no replay); they recur on use and are
  then suggested. A manual backfill is possible by deleting the state file *and* setting the
  offset to 0, documented but not automated.
- [Telegram send of 💡 fails] → Status stays `observed`; retried next tick.
- [A gated run waits forever and blocks the queue] → It is visible as the only in-flight run; the
  admin decides with ▶️ / ❌. A reminder or timeout is left for later.
- [Handler map regex misses a registration style] → Falls back to "internal code (`<func>`)";
  tests pin the current registration style.
- [PLAN agent writes an unhelpful impact] → It is still a model's estimate; the 🔀 diff and
  sensitive-path list remain the ground truth before ✅.

## Migration Plan

`CREATE TABLE IF NOT EXISTS` runs at bot start (`db.init_database`). Merge, restart the bot. The
first tick creates the offset file at the log's current end. Rollback: revert the merge; the
unused table is harmless.
