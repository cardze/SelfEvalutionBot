## Context

The SelfEvaluationBot is a Telegram bot that collects user feedback through a two-step conversation flow: users report a bug or feature gap, then suggest a fix or new feature. Currently, feedback is only logged as text lengths and discarded after the session—there is no persistent record.

The team wants to build a feedback memory system using PostgreSQL as the primary data store. This is the foundation for future capabilities like feedback analysis, trend detection, and agent-driven retrieval. The current codebase is Python-based with python-telegram-bot library; it runs on a developer's machine or a cloud VPS.

**Constraints:**
- Local development environment must work with a local Postgres instance
- Feedback handling must remain synchronous and fast (no background queues yet)
- User-facing Telegram prompts must not change
- The storage layer should be decoupled from bot logic for future replacement or extension

## Goals / Non-Goals

**Goals:**
- Persist completed feedback submissions (bug + suggestion) with full text content
- Record conversation lifecycle events (started, cancelled, submitted) for audit trails
- Initialize Postgres schema at bot startup with validation
- Provide a retrieval service boundary (contract only) for future agent/dashboard consumption
- Support local-first development with clear setup documentation
- Establish a stable data model that can evolve without breaking existing rows

**Non-Goals:**
- Admin UI or user-facing commands to query/export feedback (retrieval is service-layer contract only)
- Real-time sync to cloud or multi-region replication
- Encryption-at-rest or field-level encryption (defer to infrastructure layer)
- Analytics aggregations or materialized views (defer to future analysis layer)
- User data retention policy or GDPR/privacy mechanisms (defer to compliance sprint)
- Async event bus or background job queue (keep handlers synchronous)

## Decisions

### 1. Database Driver: psycopg3 (sync mode)
**Choice:** Use psycopg3 in synchronous mode.
**Rationale:** The existing bot handlers are async, but persistence writes are quick (~10ms per row). Keeping the driver sync and wrapping writes in `asyncio.to_thread()` is simpler than introducing an async Postgres driver, avoids connection pool complexity, and allows gradual migration to async-to-async later. Sync driver is mature and well-tested.
**Alternatives considered:**
- psycopg3 async: Would require async connection pool and more threading complexity; deferred for now.
- SQLAlchemy ORM: Would add 40+ KB dependency and learning curve; raw SQL is sufficient for simple schema.

### 2. Schema: Two tables (feedback_submissions, feedback_events)
**Choice:** Separate tables for submissions and events, with user_id as the primary join key.
**Rationale:** Keeps the schema simple and decoupled—events are immutable audit records, submissions are completed feedback. This supports future scenarios like re-opening or annotating feedback without mutation. Normalizing prevents data duplication if a user submits multiple times.
**Schema sketch:**
```
feedback_submissions
  - id (uuid)
  - user_id (int)
  - bug_text (text)
  - suggestion_text (text)
  - created_at (timestamp)

feedback_events
  - id (uuid)
  - user_id (int)
  - event_type (enum: started, cancelled, submitted)
  - feedback_submission_id (uuid, nullable—null for started/cancelled)
  - created_at (timestamp)
```
**Alternatives considered:**
- Single table with nullable suggestion_text: Less explicit about state; mixing submissions and events pollutes the event stream.
- JSON column for event payload: Adds query complexity and schema ambiguity; two tables are clearer.

### 3. Database Connection: Environment variables + startup validation
**Choice:** Load Postgres connection settings (host, port, name, user, password) from environment variables. Validate and initialize connection pool at bot startup.
**Rationale:** Aligns with existing TELEGRAM_BOT_TOKEN pattern. Fail fast if DB is unreachable before handlers are added. Supports local dev and cloud deployment without code changes.
**Variables:**
```
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=feedback_bot
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<secret>
```
**Alternatives considered:**
- Connection string in config file: Less portable; environ is standard for 12-factor apps.
- Runtime lazy initialization: Risks silent failures during first feedback submission; startup validation is better.

### 4. Schema Initialization: SQL bootstrap file
**Choice:** Ship a single `sql/init.sql` file that creates schema on startup if tables don't exist.
**Rationale:** Simple, idempotent, and works locally. Avoids Alembic or migration tooling complexity for now. The schema is unlikely to change in Phase 1.
**Alternatives considered:**
- Alembic: Overkill for a single schema; can add later.
- Auto-generate with SQLAlchemy: Would require ORM models; we're using raw SQL.

### 5. Persistence Integration: Write-on-success + silent log-on-failure
**Choice:** Write feedback and events to DB after handler logic completes. If writes fail, log the error and continue (don't block user response).
**Rationale:** Feedback collection should remain user-responsive even if DB is temporarily down. Logging failures lets ops detect and fix issues. This aligns with feedback being secondary to the core bot flow.
**Alternatives considered:**
- Fail the handler if DB writes fail: Too aggressive; a temporary DB outage shouldn't break the bot.
- Queue writes asynchronously: Adds complexity; writes are fast enough to stay inline.

### 6. Retrieval Boundary: Service layer with read contract only (no implementation yet)
**Choice:** Define a `FeedbackService.get_feedback()` method signature and docstring, but leave the body empty (or raise NotImplementedError).
**Rationale:** Unblocks future agent-driven queries without implementing read commands. Forces architectural clarity and separates retrieval from submission.
**Example:**
```python
class FeedbackService:
    def store_submission(self, user_id, bug, suggestion): ...
    def record_event(self, user_id, event_type, submission_id=None): ...
    def get_feedback(self, filters=None):  # Contract only
        raise NotImplementedError("Retrieval to be added in next phase")
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| **DB connection fails at startup** | Validate connection and display clear error message with connection string format. Document required env vars in README. |
| **User submits feedback while DB is down** | Write fails silently and logs error. User gets success response anyway (acceptable for feedback). Ops monitors logs for DB outages. |
| **Schema drifts between local and prod** | Ship SQL init file as source of truth. No manual schema changes; all changes go through sql/ versioning (future Alembic integration). |
| **Postgres credentials in environment** | Only acceptable for local dev. Document how to use Postgres managed service or Secrets Manager in prod. This spike does not include secret management. |
| **Event table grows unbounded** | Defer retention policy to compliance sprint. Document that this is a known data governance gap. |
| **Naive timestamp handling (UTC vs local)** | Always use UTC timestamps; document in schema comments. Timezone confusion is a common bug—be explicit. |

## Migration Plan

**Phase 1: Local Development**
1. Developer installs Postgres locally (or uses Docker container)
2. Sets environment variables
3. Runs bot; startup creates schema if missing
4. Feedback flow creates rows in both tables
5. No schema or deployment steps beyond env vars

**Phase 2: Production Promotion (future)**
1. Point bot to managed Postgres (AWS RDS, Render, etc.)
2. Same environment variables work unchanged
3. Optional: Run `sql/init.sql` manually to seed schema in prod before deploy
4. No code changes needed

**Rollback:** If Postgres fails, set `DB_DISABLED=true` env var to skip writes (handler checks this flag and logs warning). Feedback collection continues but data isn't stored. This is a coarse kill-switch; refine later if needed.

## Open Questions

1. **Should we hash user IDs?** Currently storing Telegram user_id as-is. Privacy question: is Telegram user_id considered PII? Defer decision to compliance, but document as a known gap.
2. **Event retention policy:** How long should events be kept? Feedback submissions? No policy yet; log as tech debt.
3. **Async driver upgrade:** When is it worth moving psycopg3 to async mode? Needs performance baseline; defer for now.
4. **Retrieval filtering:** What query patterns will agents/dashboards need? (user_id? date range? keyword search?) Defer until agent work starts; placeholder in service contract is sufficient.
