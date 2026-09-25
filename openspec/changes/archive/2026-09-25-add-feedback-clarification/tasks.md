## 0. Setup

- [x] 0.1 Create branch `add-feedback-clarification` off `main` (per AGENTS.md branch rule)

## 1. Schema

- [x] 1.1 In `sql/init.sql`, change `feedback_events.event_type` to `VARCHAR(50)` in the `CREATE TABLE` and update its comment
- [x] 1.2 Append the idempotent `ALTER COLUMN ... TYPE VARCHAR(50)` and the drop-and-add `feedback_events_event_type_check` constraint (design D3)
- [x] 1.3 Add the `feedback_clarifications` table with UNIQUE on submission, the status/answer_source CHECKs, the timestamp-consistency CHECKs and `TIMESTAMPTZ` columns (design D1)
- [x] 1.4 Run `init.sql` twice against the local DB and confirm both runs succeed and the existing 14 events still pass the constraint

## 2. Event integrity (storage.py)

- [x] 2.1 Add module-level `EVENT_TYPES` tuple including `clarification_requested` and `clarified`; make `record_event` use it
- [x] 2.2 Add `tests/test_event_types.py`: parse the CHECK list from `sql/init.sql` and assert it equals `set(EVENT_TYPES)`

## 3. Clarification storage (storage.py)

- [x] 3.1 `create_clarification(submission_id, question, options)`: insert `pending_approval`; raise on UNIQUE violation, missing submission, or resolved submission (do not swallow)
- [x] 3.2 `get_clarification(clarification_id)` and lookup by `(user_id, reply_prompt_message_id)`
- [x] 3.3 Conditional transitions that return whether they applied: `mark_sent`, `revert_to_pending`, `mark_discarded`, `mark_answered(answer_text, answer_source)`, each guarded by `WHERE status = <expected>`
- [x] 3.4 Setters for `admin_message_id`, `question_message_id`, `reply_prompt_message_id`
- [x] 3.5 `get_actionable_feedback()`: exclude resolved and `pending_approval`/`sent`; answered first by `answered_at`, then by `created_at`; include clarification context; return `pending_approval` and `parked` counts
- [x] 3.6 `is_resolved(submission_id)` helper used by the answer path and by `ask.py`

## 4. Shared Telegram delivery

- [x] 4.1 Create a small module (e.g. `clarify.py`) with `validate_draft(question, options)` (2–4 options, 1–30 characters each, no duplicates, question 1–500 characters)
- [x] 4.2 `send_admin_preview(bot, clarification)`: plain text with submitter ID, feedback, question and options, plus `apv:<id>:y` / `apv:<id>:n` buttons; store `admin_message_id`
- [x] 4.3 `deliver_question(bot, clarification)`: `mark_sent` → send plain text with option buttons `clr:<id>:<idx>` plus `clr:<id>:x`; on success store `question_message_id` and record `clarification_requested`; on failure `revert_to_pending` and re-raise
- [x] 4.4 Add `ADMIN_USER_ID` loading with a clear error if it is missing when needed

## 5. ask.py CLI

- [x] 5.1 `ask.py next`: print JSON from `get_actionable_feedback()`
- [x] 5.2 `ask.py draft <submission_id> --question … --option … [--yes]`: validate → create row → preview (default) or deliver (`--yes`); non-zero exit with a message on any failure; nothing sent if the DB write fails
- [x] 5.3 `ask.py resend-preview <submission_id>`: re-send the preview for an existing `pending_approval` row
- [x] 5.4 Load `.env` via `load_dotenv()` like `bot.py`

## 6. Bot handlers (bot.py)

- [x] 6.1 Approval `CallbackQueryHandler` (pattern `^apv:`): reject non-admin; ✅ → `deliver_question`, then edit the preview to "Sent" (or report the failure); ❌ → `mark_discarded`, then edit the preview to "Discarded"; no-op if no longer `pending_approval`
- [x] 6.2 Answer `CallbackQueryHandler` (pattern `^clr:`): verify the tapper is the submitter; option → `mark_answered('option')` + `clarified` event + edit message; `x` → send ForceReply prompt + store its ID; already answered → "Already answered, thanks!"; resolved → "Thanks! This was already addressed."
- [x] 6.3 Free-text reply `MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND)` in group -1: look up by `(from_user.id, reply_to_message.message_id)`; on match store the answer (`free_text`) + `clarified` event + confirmation, then raise `ApplicationHandlerStop`; on no match return normally
- [x] 6.4 Register the handlers so the reply handler runs before the `/feedback` ConversationHandler

## 7. Tests

- [x] 7.1 `validate_draft` tests covering each rejection rule and a valid draft
- [x] 7.2 Handler tests with fakes (same style as `tests/test_command_hints.py`): non-admin approval ignored; wrong-user answer ignored; option tap stores the answer; "Something else" sends ForceReply; matched reply stops propagation; unmatched reply passes through
- [x] 7.3 Queue-ordering test for `get_actionable_feedback` (DB-backed and skipped if Postgres is unavailable, or with SQL logic tested against a fake)
- [x] 7.4 Run the full test suite

## 8. Planner skill and agents

- [x] 8.1 Rewrite `.github/skills/planner-fetch-feedback/SKILL.md`: procedure per design D7, remove the raw SQL and the "no done flag" assumption, add the question-writing rules, add `Clarification:` to the output format
- [x] 8.2 Copy the skill to `.claude/skills/planner-fetch-feedback/SKILL.md`
- [x] 8.3 Reference the skill in `.claude/agents/planner.md` and `.github/agents/planner.agent.md`

## 9. Config and docs

- [x] 9.1 Add `ADMIN_USER_ID` to `.env.example`
- [x] 9.2 README: document `ADMIN_USER_ID`, the admin `/start` requirement, the clarification flow and `ask.py` usage; fix the setup note that implies `.env` needs manual export
- [x] 9.3 AGENTS.md: remove the `resolved` row from "Known out-of-process changes" (now covered by `feedback-event-integrity`)

## 10. End-to-end check

- [x] 10.1 With the bot running, draft a clarification for the open "notice function" submission via `ask.py draft`; approve in Telegram; answer with an option; confirm `ask.py next` lists it first with the answer
- [x] 10.2 Repeat the "Something else" path with a test submission, restart the bot between the prompt and the reply, and confirm the reply is captured
  - Covered by tests, not run live: reply lookup is DB-backed (`tests/test_actionable_queue.py::test_reply_prompt_lookup`) and the reply handler is covered in `tests/test_clarification.py`; the live E2E in 10.1 exercised the free-text path without a restart.
