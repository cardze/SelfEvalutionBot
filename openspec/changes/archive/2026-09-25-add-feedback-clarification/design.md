## Context

- `bot.py` collects feedback through a two-step `/feedback` ConversationHandler. `storage.py` (`FeedbackService`) writes to `feedback_submissions` and to an event log, `feedback_events`.
- A submission is "resolved" when a `resolved` event exists for it. `get_unresolved_feedback()` implements that rule.
- `feedback_events.event_type` is `VARCHAR(20)`, and the only list of allowed values is a hardcoded tuple in `record_event`. `record_event` swallows all exceptions.
- `sql/init.sql` runs on every startup via `db.init_database()` and is written to be safe to re-run (`CREATE ... IF NOT EXISTS`). There is no migration tool.
- The planner agent reads feedback through the `planner-fetch-feedback` skill (`.github/skills/` only). Its SQL ignores `resolved`, and it still assumes no done flag exists.
- The bot runs in polling mode with no JobQueue. `ask.py` will be a separate process that the agent invokes.

## Goals / Non-Goals

**Goals:**
- The planner can ask a feedback submitter exactly one clarifying question, with admin approval in Telegram.
- Answers, button or free text, are captured reliably across bot restarts and reopen the submission.
- Event types are enforced in the database and cannot silently drift from Python.
- The planner's definition of "actionable feedback" lives in one place (Python) and is correct.

**Non-Goals:**
- Timers, expiry or scheduled jobs of any kind.
- More than one question per submission, or follow-up questions.
- Changing `record_event` error handling for the existing `/feedback` flow.
- Converting existing tables to `TIMESTAMPTZ`, or cleaning up test rows.
- Notifying users when their feedback ships.

## Decisions

### D1. Separate `feedback_clarifications` table, with events mirroring user-visible transitions
```
feedback_clarifications
  id                       UUID PK DEFAULT gen_random_uuid()
  feedback_submission_id   UUID NOT NULL UNIQUE REFERENCES feedback_submissions(id) ON DELETE CASCADE
  question                 TEXT NOT NULL
  options                  JSONB NOT NULL            -- ["Remind me at a time I set", ...]
  status                   VARCHAR(20) NOT NULL DEFAULT 'pending_approval'
                           CHECK (status IN ('pending_approval','sent','answered','discarded'))
  answer_text              TEXT NULL
  answer_source            VARCHAR(20) NULL CHECK (answer_source IN ('option','free_text'))
  admin_message_id         BIGINT NULL               -- preview message in admin chat
  question_message_id      BIGINT NULL               -- question message in submitter chat
  reply_prompt_message_id  BIGINT NULL               -- ForceReply prompt in submitter chat
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now()
  sent_at                  TIMESTAMPTZ NULL
  answered_at              TIMESTAMPTZ NULL
  CHECK (status NOT IN ('sent','answered') OR sent_at IS NOT NULL)
  CHECK (status <> 'answered' OR (answered_at IS NOT NULL AND answer_text IS NOT NULL AND answer_source IS NOT NULL))
```
- The event log has no payload column, so the question and answer content need somewhere to live. The table holds content and workflow status. `feedback_events` records only what happened to the user: `clarification_requested` when the question is actually delivered, and `clarified` when it is answered.
- *Alternative:* add a `payload JSONB` column to `feedback_events`. Rejected because it would turn the events table into a general document store and complicate every query on it.
- `UNIQUE(feedback_submission_id)` enforces "exactly one question" at the database level, so a retrying agent cannot send two.
- The new table uses `TIMESTAMPTZ`. The mismatch with the older `TIMESTAMP` tables is accepted, and converting them is out of scope.

### D2. Lifecycle is derived; no timers
```
                      ask.py draft
                           │
                           ▼
                   ┌───────────────┐   ❌ admin    ┌───────────┐
                   │pending_approval├─────────────▶│ discarded │  submission stays actionable
                   └───────┬───────┘               └───────────┘  (planner best-guesses)
                    ✅ admin│
                           ▼
                   ┌───────────────┐                 submission PARKED
                   │     sent      │                 (not in actionable queue)
                   └───────┬───────┘
          option tap / free-text reply (any time, first wins)
                           ▼
                   ┌───────────────┐                 submission REOPENED
                   │   answered    │                 (actionable, highest priority)
                   └───────────────┘
```
Actionable queue (`FeedbackService.get_actionable_feedback`):
- **Excluded:** submissions with a `resolved` event, and submissions whose clarification is `sent` or `pending_approval`.
- **Order:** answered clarifications first (by `answered_at` ascending), then everything else by `created_at` ascending.
- Also returns counts of `pending_approval` (waiting on the admin) and `sent` (parked) items so the planner can report them.

*Alternative:* a 7-day expiry with a sweep. Rejected because not answering means we cannot proceed anyway, so parking is equivalent and needs no clock, sweep or expiry column.

### D3. `event_type` widening and CHECK constraint, both re-runnable
Appended to `init.sql` after the `CREATE TABLE` statements:
```sql
ALTER TABLE feedback_events ALTER COLUMN event_type TYPE VARCHAR(50);
ALTER TABLE feedback_events DROP CONSTRAINT IF EXISTS feedback_events_event_type_check;
ALTER TABLE feedback_events ADD CONSTRAINT feedback_events_event_type_check
  CHECK (event_type IN ('started','cancelled','submitted','resolved',
                        'clarification_requested','clarified'));
```
- The `CREATE TABLE` definition is also changed to `VARCHAR(50)`, so fresh installs and existing databases end up identical.
- Widening a varchar is metadata-only in Postgres. Dropping and re-adding the constraint re-validates all rows on each startup, which is negligible at current volume. Existing data (`started`, `cancelled`, `submitted`, `resolved`) passes.
- `storage.py` gains `EVENT_TYPES`, a module-level tuple used by `record_event`. A test parses the CHECK list out of `init.sql` and asserts it equals `EVENT_TYPES`, so drift fails CI instead of failing silently at runtime.
- *Alternative:* the database as the only gatekeeper. Rejected because the Python check gives a clear log line, and the parity test removes the cost of keeping two lists.

### D4. `ask.py` CLI is the agent's only entry point
```
python ask.py next                       → JSON: {actionable: [...], pending_approval: N, parked: N}
python ask.py draft <submission_id> \
    --question "…" --option "…" --option "…" [--option …] [--yes]
```
`draft` steps, stopping with a non-zero exit at the first failure:
1. **Validate:**
   - 2–4 options, each 1–30 characters, no duplicates
   - question 1–500 characters
   - the submission exists and is not resolved
2. **Insert** the clarification row with `pending_approval`. A UNIQUE violation means one was already asked, so exit non-zero without sending anything.
3. **Default path:** send the preview to `ADMIN_USER_ID` with ✅/❌ buttons and store `admin_message_id`.
4. **With `--yes`:** skip the preview and run the same deliver routine that ✅ triggers (D5).
- The DB write comes before any Telegram send, so a crash leaves a row that was never sent rather than a question that was sent but not recorded.
- It uses `telegram.Bot(token)` with `asyncio.run(...)`. Sending from a second process while `bot.py` polls is safe, because only `getUpdates` conflicts.
- *Alternative:* raw SQL in the skill. Rejected because it already drifted once (the `resolved` filter was missing), and one Python definition prevents a repeat.

### D5. Approval and delivery happen in `bot.py`
`callback_data` formats all fit Telegram's 64-byte limit:
- `apv:<uuid>:y` / `apv:<uuid>:n` for admin approve and discard (≈42 bytes)
- `clr:<uuid>:<idx>` for an option tap
- `clr:<uuid>:x` for "✏️ Something else"

**Approval handler:**
- Ignore the tap unless `from_user.id == ADMIN_USER_ID`.
- **✅:** run `UPDATE … SET status='sent', sent_at=now() WHERE id=? AND status='pending_approval' RETURNING …`, then send the question. The conditional update guards against a double tap.
  - **Send succeeds:** store `question_message_id` and record `clarification_requested`.
  - **Send fails:** revert to `pending_approval` and report the error to the admin.
- **❌:** conditional update to `discarded`.
- Either way, edit the admin preview to show the outcome.

**Deliver routine:** a shared function used by ✅ and `--yes`. It sends plain text with no `parse_mode`, because LLM-written text would break MarkdownV2 escaping (see commit 2f7e24e).

### D6. Answer capture: buttons plus ForceReply, handled before `/feedback`
- **Option tap:** `UPDATE … SET status='answered', answer_text=options[idx], answer_source='option', answered_at=now() WHERE id=? AND status='sent'`. Then record `clarified` and edit the question message to "Thanks! Noted: …".
- **"Something else":** send "Reply to this message with your answer." with `ForceReply` and store `reply_prompt_message_id`. The status stays `sent`.
- **Reply handler:**
  - Registered as `MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND)` in **group -1**, so it runs before the `/feedback` ConversationHandler in group 0.
  - It looks up the clarification by `(submission.user_id = from_user.id, reply_prompt_message_id = reply_to_message.message_id)`.
  - **Match:** store the answer with `answer_source='free_text'` using the same conditional update, then raise `ApplicationHandlerStop` so `/feedback` does not also consume the message.
  - **No match:** return without stopping, so normal flows are unaffected.
- **First answer wins:** the conditional `WHERE status='sent'` makes both paths atomic. A later tap or reply gets "Already answered, thanks!"
- **Already resolved:** if a `resolved` event exists when an answer arrives, store the answer but reply "Thanks! This was already addressed." The submission is not reopened, because the queue excludes resolved submissions anyway.
- *Alternative:* per-user state in `context.user_data`. Rejected because it is in memory only (no persistence configured), so it would be lost on restart, and it would conflict with `/feedback` text handling.

### D7. Planner skill rewrite
Procedure:
1. Active change check (unchanged).
2. `ask.py next`.
3. Take the first actionable item. An answered clarification means "use the answer, treat as fresh against current specs". A discarded one means "best guess, recorded as an assumption".
4. Apply the ambiguity gate: *would different readings lead to different features?* Ask only if yes and no clarification row exists.
5. Draft using the question-writing rules:
   - quote the user's words
   - mutually exclusive options
   - plain language
   - match the feedback's language
6. After drafting, report "awaiting approval" and move on to the next actionable item.

Other changes:
- Remove the stale "no done flag" assumption and the raw SQL.
- Add `Clarification:` to the output format.
- Copy the skill to `.claude/skills/planner-fetch-feedback/`, and reference it from both planner agent files.

## Risks / Trade-offs

- [The admin never acts on a preview, so the submission stalls in `pending_approval`] → `ask.py next` reports the pending count, and the planner surfaces it every run.
- [Tapping ✅ succeeds in the DB but Telegram send fails] → Revert to `pending_approval`, report to the admin, and allow a retry by tapping ✅ again.
- [`ask.py` inserts the row but the preview send fails] → The row stays `pending_approval` with no preview. `ask.py` exits non-zero with the error. Recovery: `ask.py resend-preview <submission_id>` (small subcommand) re-sends the preview for an existing `pending_approval` row.
- [The user dismisses the ForceReply and types a normal message] → Not captured. The prompt text tells them to reply to it, and the buttons remain usable.
- [Forged callback data] → Approval requires the admin ID. Answer handlers verify that `callback_query.from_user.id` equals the submission's `user_id`.
- [The drop-and-add CHECK runs on every startup] → Negligible now. Revisit if `feedback_events` grows large, or when a migration tool is introduced.
- [The submitter blocked the bot] → Send fails and is handled like any send failure. The admin is told, and can ❌ to discard.
- [Old `TIMESTAMP` and new `TIMESTAMPTZ` columns are mixed] → No cross-table time comparisons are needed in this change.

## Migration Plan

1. Deploy code and `init.sql`. Startup widens the column, adds the CHECK and creates the new table. There is no data backfill.
2. Set `ADMIN_USER_ID` in `.env`. The admin sends `/start` to the bot once.
3. Rollback: revert the code. The new table and wider column are harmless to old code. The CHECK constraint still allows every old event type.

## Open Questions

- None blocking. All decisions were settled during exploration (see the conversation that led to this change).
