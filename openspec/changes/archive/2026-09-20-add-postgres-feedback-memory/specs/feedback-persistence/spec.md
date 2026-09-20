## ADDED Requirements

### Requirement: Store completed feedback submissions
The system SHALL persist completed feedback submissions (bug report + suggestion pair) to PostgreSQL with full text content, user metadata, and timestamps.

#### Scenario: User completes feedback workflow
- **WHEN** a user completes the two-step feedback form and confirms submission
- **THEN** a new row is inserted into feedback_submissions with user_id, bug_text, suggestion_text, and created_at timestamp

#### Scenario: Multiple submissions from same user
- **WHEN** a user submits feedback multiple times
- **THEN** each submission creates a new row (no duplicate detection or updates)

#### Scenario: Submission persists across bot restarts
- **WHEN** the bot restarts or redeploys
- **THEN** previously stored submissions remain in the database unchanged

### Requirement: Record conversation lifecycle events
The system SHALL log all feedback conversation state transitions (started, cancelled, submitted) as immutable audit events linked to the user and (if applicable) their submission.

#### Scenario: Event recorded when feedback starts
- **WHEN** a user invokes /feedback command
- **THEN** a new event row is inserted with event_type='started' and user_id

#### Scenario: Event recorded when feedback is cancelled
- **WHEN** a user runs /cancel during feedback flow
- **THEN** a new event row is inserted with event_type='cancelled' and user_id, with no submission_id

#### Scenario: Event recorded when feedback is submitted
- **WHEN** user completes step 2 and feedback is stored
- **THEN** a new event row is inserted with event_type='submitted', user_id, and feedback_submission_id

#### Scenario: Events remain even if submission storage fails
- **WHEN** a submission cannot be written to the database (e.g., DB connection lost)
- **THEN** the started event still exists in the database; the submitted event is not created; an error is logged

### Requirement: Validate database connectivity at startup
The system SHALL attempt to connect to PostgreSQL during bot initialization and fail with a clear error message if the database is unreachable.

#### Scenario: Database is reachable
- **WHEN** the bot starts and Postgres is running
- **THEN** the bot initializes the connection pool and proceeds to start accepting messages

#### Scenario: Database is unreachable
- **WHEN** the bot starts and Postgres is not reachable (host unreachable, port refused, or credentials invalid)
- **THEN** the bot exits with an error message indicating which connection parameter is incorrect (host, port, database name, or credentials)

#### Scenario: Database credentials provided via environment
- **WHEN** the bot starts
- **THEN** it reads Postgres connection details from environment variables (POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD)

### Requirement: Initialize database schema automatically
The system SHALL create required tables on startup if they do not exist, using an idempotent SQL script.

#### Scenario: Schema does not exist on first run
- **WHEN** the bot starts and tables feedback_submissions and feedback_events do not exist
- **THEN** the bot executes the schema initialization script and creates both tables

#### Scenario: Schema already exists
- **WHEN** the bot starts and tables already exist
- **THEN** the initialization is skipped and no errors occur

#### Scenario: Partial schema (one table exists, other missing)
- **WHEN** one table exists but the other does not (e.g., interrupted previous startup)
- **THEN** the initialization script idempotently creates the missing table without affecting the existing one

### Requirement: Feedback handler integration without UX changes
The system SHALL integrate persistence calls into existing feedback handlers while keeping user-facing prompts, flow, and response formatting identical.

#### Scenario: Prompt text remains unchanged
- **WHEN** user runs /feedback, Step 1, or Step 2
- **THEN** the bot displays exactly the same prompts and markdown formatting as before persistence was added

#### Scenario: User data lifecycle remains unchanged
- **WHEN** conversation progresses through steps or is cancelled
- **THEN** context.user_data is managed identically to before (populated, used, cleared at end)

#### Scenario: Persistence failure does not block conversation
- **WHEN** a database write fails during handler execution
- **THEN** the bot logs the error, still sends the user the success message, and continues accepting new commands

### Requirement: Retrieval service boundary (contract)
The system SHALL expose a service interface for querying stored feedback that is currently not implemented but clearly contracts for future use.

#### Scenario: Service interface exists with method signatures
- **WHEN** the codebase is inspected
- **THEN** a FeedbackService class exists with methods store_submission(), record_event(), and get_feedback() (read methods raise NotImplementedError with a TODO)

#### Scenario: Future retrieval can be added without changing persistence
- **WHEN** retrieval needs are clarified in a future sprint
- **THEN** the get_feedback() contract can be implemented without modifying storage or event recording logic
