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
    event_type VARCHAR(20) NOT NULL,  -- 'started', 'cancelled', 'submitted'
    feedback_submission_id UUID REFERENCES feedback_submissions(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Create index on user_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_feedback_events_user_id 
    ON feedback_events(user_id);

-- Create index on feedback_submission_id for linking
CREATE INDEX IF NOT EXISTS idx_feedback_events_submission_id 
    ON feedback_events(feedback_submission_id);
