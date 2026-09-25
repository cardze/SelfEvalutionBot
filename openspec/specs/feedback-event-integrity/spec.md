# feedback-event-integrity Specification

## Purpose
Define the allowed feedback event types, including `resolved` as the done marker, and keep them enforced consistently in Python and PostgreSQL.
## Requirements
### Requirement: Allowed feedback event types
The system SHALL accept only these values for `feedback_events.event_type`:
- `started`, `cancelled`, `submitted`, `resolved`
- `clarification_requested`, `clarified`
- `wont_do`

The column SHALL hold at least 50 characters.

#### Scenario: Known event type
- **WHEN** an event with type `clarification_requested` is recorded
- **THEN** it is stored successfully

#### Scenario: Won't-do event
- **WHEN** an event with type `wont_do` is recorded for a submission
- **THEN** it is stored successfully

#### Scenario: Unknown event type rejected in Python
- **WHEN** `record_event` is called with a type that is not in `EVENT_TYPES`
- **THEN** it returns `False`, logs a warning, and does not touch the database

#### Scenario: Unknown event type rejected in database
- **WHEN** a row with an event type outside the allowed set is inserted directly into `feedback_events`
- **THEN** PostgreSQL rejects the insert with a CHECK constraint violation

### Requirement: Resolved event marks a submission done
A submission SHALL be considered resolved when a `feedback_events` row with `event_type = 'resolved'` references it. `FeedbackService.resolve_submission(submission_id)` SHALL record that event.

#### Scenario: Resolve an existing submission
- **WHEN** `resolve_submission` is called with the ID of an existing submission
- **THEN** a `resolved` event is recorded with the submission's user ID, and the method returns `True`

#### Scenario: Resolve a missing submission
- **WHEN** `resolve_submission` is called with an ID that does not exist
- **THEN** no event is recorded and the method returns `False`

### Requirement: Schema initialization stays idempotent
`sql/init.sql` SHALL bring both fresh and existing databases to the same `feedback_events` schema, and SHALL be safe to run on every startup.

#### Scenario: Existing database with narrow column
- **WHEN** `init.sql` runs against a database where `event_type` is `VARCHAR(20)`
- **THEN** the column becomes `VARCHAR(50)` and the event-type CHECK constraint is present

#### Scenario: Repeated startup
- **WHEN** `init.sql` runs twice in a row
- **THEN** both runs succeed and the schema is unchanged by the second

#### Scenario: Existing rows pass the constraint
- **WHEN** the CHECK constraint is added to a database containing only the original four event types
- **THEN** the constraint is created without errors

### Requirement: Python and SQL event lists stay in sync
The `EVENT_TYPES` constant in `storage.py` SHALL match the event types listed in the CHECK constraint in `sql/init.sql`, verified by an automated test that needs no database.

#### Scenario: Lists match
- **WHEN** the test suite runs
- **THEN** the parity test passes if and only if the two sets are equal

