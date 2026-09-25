-- Initialize feedback bot database schema
-- Idempotent: safe to run multiple times

-- Create feedback_submissions table if not exists
CREATE TABLE IF NOT EXISTS feedback_submissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,
    bug_text TEXT NOT NULL,
    suggestion_text TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on user_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_feedback_submissions_user_id 
    ON feedback_submissions(user_id);

-- Create feedback_events table if not exists
CREATE TABLE IF NOT EXISTS feedback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id BIGINT NOT NULL,
    event_type VARCHAR(50) NOT NULL,  -- see feedback_events_event_type_check below
    feedback_submission_id UUID REFERENCES feedback_submissions(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on user_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_feedback_events_user_id 
    ON feedback_events(user_id);

-- Create index on feedback_submission_id for linking
CREATE INDEX IF NOT EXISTS idx_feedback_events_submission_id 
    ON feedback_events(feedback_submission_id);

-- Widen event_type on databases created before VARCHAR(50) (no-op if already wide)
ALTER TABLE feedback_events ALTER COLUMN event_type TYPE VARCHAR(50);

-- Allowed event types; keep in sync with storage.EVENT_TYPES (enforced by tests/test_event_types.py)
ALTER TABLE feedback_events DROP CONSTRAINT IF EXISTS feedback_events_event_type_check;
ALTER TABLE feedback_events ADD CONSTRAINT feedback_events_event_type_check
    CHECK (event_type IN ('started', 'cancelled', 'submitted', 'resolved',
                          'clarification_requested', 'clarified', 'wont_do'));

-- One clarifying question per feedback submission
CREATE TABLE IF NOT EXISTS feedback_clarifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_submission_id UUID NOT NULL UNIQUE
        REFERENCES feedback_submissions(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    options JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending_approval'
        CHECK (status IN ('pending_approval', 'sent', 'answered', 'discarded')),
    answer_text TEXT,
    answer_source VARCHAR(20) CHECK (answer_source IN ('option', 'free_text')),
    admin_message_id BIGINT,
    question_message_id BIGINT,
    reply_prompt_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at TIMESTAMPTZ,
    answered_at TIMESTAMPTZ,
    CHECK (status NOT IN ('sent', 'answered') OR sent_at IS NOT NULL),
    CHECK (status <> 'answered'
           OR (answered_at IS NOT NULL AND answer_text IS NOT NULL AND answer_source IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_feedback_clarifications_reply_prompt
    ON feedback_clarifications(reply_prompt_message_id);

-- Autonomous feedback runner: one row per runner-built change (see runner/)
CREATE TABLE IF NOT EXISTS auto_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feedback_submission_id UUID NOT NULL
        REFERENCES feedback_submissions(id) ON DELETE CASCADE,
    branch VARCHAR(100) NOT NULL,
    workspace_path TEXT NOT NULL,
    change_name VARCHAR(100),
    stage VARCHAR(30) NOT NULL DEFAULT 'planning'
        CHECK (stage IN ('planning', 'planned', 'building', 'awaiting_decision',
                         'merged', 'rejected', 'failed')),
    decision VARCHAR(20) CHECK (decision IN ('merge', 'reject', 'changes')),
    decision_note TEXT,
    merge_request_message_id BIGINT,
    note_prompt_message_id BIGINT,
    build_attempts INT NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- At most one run in flight
CREATE UNIQUE INDEX IF NOT EXISTS uq_auto_runs_single_flight
    ON auto_runs ((true)) WHERE stage NOT IN ('merged', 'rejected');
