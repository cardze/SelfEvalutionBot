## 1. Setup and Dependencies

- [x] 1.1 Add psycopg3 and python-dotenv to requirements.txt
- [x] 1.2 Create sql/init.sql with schema for feedback_submissions and feedback_events tables
- [x] 1.3 Create openspec/config.yaml project context documenting tech stack and conventions

## 2. Database Connection and Initialization

- [x] 2.1 Create db.py module with PostgreSQL connection pool initialization
- [x] 2.2 Implement startup validation: connect, run init.sql if needed, return pool or raise clear error
- [x] 2.3 Add environment variable parsing (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD)
- [ ] 2.4 Test startup failure scenarios: connection refused, invalid credentials, missing database

## 3. Storage Service Layer

- [x] 3.1 Create storage.py module with FeedbackService class
- [x] 3.2 Implement store_submission(user_id, bug_text, suggestion_text) → inserts row into feedback_submissions
- [x] 3.3 Implement record_event(user_id, event_type, submission_id=None) → inserts row into feedback_events
- [x] 3.4 Implement get_feedback() stub that raises NotImplementedError (contract for future)
- [x] 3.5 Add error handling: log failures, don't raise exceptions to caller (write-on-success + silent log)

## 4. Integration into Bot Handlers

- [x] 4.1 Import FeedbackService in bot.py and initialize global instance
- [x] 4.2 Wire feedback_start handler: call record_event(user_id, "started") before returning STEP_BUG
- [x] 4.3 Wire feedback_cancel handler: call record_event(user_id, "cancelled") before returning END
- [x] 4.4 Wire feedback_suggestion handler: call store_submission() then record_event(..., "submitted") before success message
- [x] 4.5 Verify no changes to user-facing prompts, markdown, or context.user_data lifecycle

## 5. Database Initialization at Bot Startup

- [x] 5.1 Update main() in bot.py to initialize database before building Telegram Application
- [x] 5.2 Ensure startup fails fast with clear error message if database is unreachable
- [x] 5.3 Ensure schema is idempotent (re-runs without error if tables already exist)

## 6. Documentation and Setup Instructions

- [x] 6.1 Update README.md with "Database Setup" section covering local Postgres installation
- [x] 6.2 Document required environment variables (POSTGRES_* and TELEGRAM_BOT_TOKEN)
- [x] 6.3 Add example .env file (without secrets)
- [x] 6.4 Document how to run bot locally with Postgres for development

## 7. Testing and Verification

- [x] 7.1 Manual test: start bot and verify no startup errors with correct env vars
- [x] 7.2 Manual test: complete /feedback flow and verify feedback_submissions row exists
- [x] 7.3 Manual test: verify started and submitted event rows exist after completion
- [x] 7.4 Manual test: run /cancel and verify started + cancelled events exist (no submission row)
- [x] 7.5 Manual test: restart bot and verify data persists
- [x] 7.6 Manual test: set invalid DB credentials and verify startup error is clear
- [x] 7.7 Verify existing Telegram prompts, flow, and user_data behavior are unchanged
