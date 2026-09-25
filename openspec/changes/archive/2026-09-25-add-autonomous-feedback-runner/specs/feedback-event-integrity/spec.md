## MODIFIED Requirements

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
