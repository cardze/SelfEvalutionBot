## Why

The bot currently collects valuable user feedback but loses it immediately after each conversation ends. Feedback is only logged as text lengths and never stored for later analysis, making it impossible to track patterns, respond to issues, or build context over time. Adding persistent storage unlocks the ability to remember feedback, analyze trends, and build future capabilities like intelligent suggestions or automated issue routing.

## What Changes

- Add PostgreSQL persistence layer to store all completed feedback submissions with full text content
- Persist conversation lifecycle events (started, cancelled, submitted) for audit trails and event-driven workflows
- Extend bot startup to validate PostgreSQL connectivity and initialize schema
- Modify feedback handlers to write events and submission records without changing user-facing Telegram prompts or UX
- Add environment variable configuration for database connection alongside existing token setup
- Introduce a retrieval service interface (contract only, no admin commands yet) to support future agent-driven query capabilities

## Capabilities

### New Capabilities

- `feedback-persistence`: Store user feedback submissions and conversation events in PostgreSQL with structured schema, supporting write operations for submission and event recording, and read-only contract for future retrieval by agents or dashboards

### Modified Capabilities

<!-- No existing capabilities have requirement changes; this is additive. -->

## Impact

- **Code**: New storage module/service, database initialization and connection pooling in bot startup
- **APIs**: Persistence boundary (submission writer, event recorder, optional future retriever)
- **Dependencies**: PostgreSQL driver (psycopg3 or equivalent), optional migration tooling
- **Systems**: Local Postgres required for development and testing; production assumes managed Postgres or self-hosted instance
- **Data lifecycle**: User feedback and event data retained indefinitely in Postgres (no retention policy defined yet)
- **Deployment**: Added environment variables (DB host, port, name, credentials) required at startup
