## Why

Feedback often arrives too vague to act on. The open submission "I want to have a notice function… notify me when the times come" could mean personal reminders, recurring notices, or feedback-status updates. Today the planner can only guess, and nothing lets the bot ask the submitter what they meant. Without a question-and-answer channel, the self-improvement loop runs in one direction only, and a wrong guess ends up in a proposal.

## What Changes

- The planner can request **one clarifying question** per feedback submission, with 2–4 options it writes itself.
- A new CLI, `ask.py`, validates the draft, stores it, and sends a **preview to the admin in Telegram** with ✅ Send / ❌ Discard buttons. Nothing reaches a user without admin approval unless `--yes` is passed.
- On ✅, the bot sends the question to the submitter as inline buttons plus "✏️ Something else". The free-text path uses ForceReply, and the link between prompt and reply is stored in the DB so it survives restarts.
- Sending a question **parks** the submission. There is no timer. An answer at any time **reopens** it, and the planner picks answered items before older ones. An answer to an already-resolved submission is acknowledged and does not reopen it.
- Discard counts as the one question. The submission stays actionable and the planner proceeds with a best-guess interpretation.
- Schema:
  - New `feedback_clarifications` table: a UNIQUE constraint per submission, and CHECK constraints on status and timestamps.
  - `feedback_events.event_type` widened to `VARCHAR(50)`, with a CHECK constraint on the allowed event types.
  - New event types `clarification_requested` and `clarified`.
  - The existing `resolved` event type, previously added without an OpenSpec change (see AGENTS.md), is now documented.
- The `planner-fetch-feedback` skill is rewritten:
  - It adds an ambiguity check, `ask.py` usage and answered-first ordering.
  - It fixes a stale query that ignored `resolved`.
  - It uses Python (`ask.py --next`) instead of raw SQL as the single definition of "actionable".
  - It is made available to the Claude Code planner as well as Copilot.
- New env var `ADMIN_USER_ID`.

## Capabilities

### New Capabilities
- `feedback-clarification`: Drafting, admin approval, delivery, and answer capture for one clarifying question per feedback submission. Also covers feedback lifecycle state: parked, reopened, and actionable-queue rules.
- `feedback-event-integrity`: The allowed set of feedback event types, enforced in both Python and PostgreSQL and kept in sync by a test. Also documents the existing `resolved` event.
- `planner-feedback-triage`: How the planner selects the next feedback item, decides whether to ask for clarification, and uses answers.

### Modified Capabilities
<!-- none: feedback-persistence was archived without being synced to openspec/specs; its event-type behavior is captured in feedback-event-integrity -->

## Impact

- **Code**:
  - `bot.py`: new callback-query and reply handlers, registered before the `/feedback` ConversationHandler.
  - `storage.py`: new clarification methods, an `EVENT_TYPES` constant, and an actionable-queue query.
  - New `ask.py` CLI.
- **Schema**: `sql/init.sql` gets an idempotent ALTER plus drop-and-add CHECK on `feedback_events`, and the new table.
- **Config**: `ADMIN_USER_ID` in `.env` / `.env.example` / README. The admin must have started a chat with the bot.
- **Agents/skills**:
  - `.github/skills/planner-fetch-feedback/SKILL.md` is rewritten and mirrored into `.claude/skills/`.
  - `.claude/agents/planner.md` and `.github/agents/planner.agent.md` reference the skill.
- **Dependencies**: none new. `python-telegram-bot` already supports inline keyboards, callback queries and ForceReply.
- **Out of scope**:
  - Error swallowing in `record_event` for the existing `/feedback` flow
  - Converting the old tables to `TIMESTAMPTZ`
  - Test-row cleanup
  - "Your feature shipped" notifications
  - The notice/reminder feature itself, which becomes the first real test of this change
