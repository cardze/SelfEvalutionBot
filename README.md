# SelfEvaluationBot

A Telegram bot that evolves by users' feedback.

## Features

- `/start` — Welcome message.
- `/feedback` — Two-step feedback form:
  1. **What bug or current feature didn't meet your expectation.**
  2. **The way you suggest to fix the bug or create a new feature.**
- `/cancel` — Cancel an in-progress feedback session.

## Database Setup (Local Development)

This bot requires PostgreSQL to store feedback submissions and conversation events.

### Prerequisites

- **PostgreSQL 12+** installed and running locally

### Setup PostgreSQL

1. **Install PostgreSQL** (if not already installed)
   ```bash
   # macOS (using Homebrew)
   brew install postgresql@15

   # Ubuntu/Debian
   sudo apt-get install postgresql postgresql-contrib

   # Or use Docker
   docker run --name feedback-db -e POSTGRES_PASSWORD=postgres -d -p 5432:5432 postgres:15
   ```

2. **Create the feedback database**
   ```bash
   createdb feedback_bot
   ```

3. **Verify connection**
   ```bash
   psql -U postgres -d feedback_bot -c "SELECT 1"
   ```

## Setup

1. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment variables**

   Copy `.env.example` to `.env` in the project root and fill in the values.
   `bot.py` and `ask.py` load `.env` automatically, so no manual `export` is needed
   (variables already set in your shell take precedence):
   ```bash
   # .env (never commit with real values)
   TELEGRAM_BOT_TOKEN="your-bot-token-here"
   ADMIN_USER_ID=123456789
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=feedback_bot
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=postgres
   ```

3. **Run the bot**

   The bot will automatically initialize the database schema on first run:
   ```bash
   python bot.py
   ```

   If you see `✓ Database initialization complete`, the schema is ready.

## Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | — | ✓ | Your Telegram bot token from BotFather |
| `ADMIN_USER_ID` | — | for clarifications | Telegram user id that approves clarification questions. The admin must `/start` the bot once. |
| `POSTGRES_HOST` | `localhost` | | PostgreSQL server hostname |
| `POSTGRES_PORT` | `5432` | | PostgreSQL server port |
| `POSTGRES_DB` | `feedback_bot` | | Database name |
| `POSTGRES_USER` | `postgres` | | PostgreSQL username |
| `POSTGRES_PASSWORD` | `` | | PostgreSQL password |

## Running the Bot

Once environment is configured and PostgreSQL is running:

```bash
python bot.py
```

The bot will:
1. Validate PostgreSQL connectivity
2. Initialize database schema (idempotent)
3. Start polling for Telegram messages
4. Store all feedback submissions and events in the database

## Feedback Clarifications

When feedback is ambiguous, the planner agent can ask the submitter **one** clarifying question.

```
planner ──▶ python ask.py draft … ──▶ preview to ADMIN_USER_ID  [✅ Send] [❌ Discard]
                                             │ ✅
                                             ▼
                          submitter gets the question as buttons + "✏️ Something else"
                                             │ tap or reply (any time)
                                             ▼
                          answer stored ──▶ submission back at the front of the queue
```

- A sent question **parks** the submission. There is no timer; an answer at any time reopens it.
- ❌ Discard means "don't ask": the planner proceeds with a best-guess assumption.
- Answers are stored in `feedback_clarifications`; the event log gets `clarification_requested` and `clarified`.

CLI (used by the planner; see `.claude/skills/planner-fetch-feedback/SKILL.md`):

```bash
python ask.py next                                   # actionable queue as JSON
python ask.py draft <submission_id> \
    --question "About your idea \"…\": what did you mean?" \
    --option "Remind me at a time I set" --option "Recurring notice"
python ask.py resend-preview <submission_id>         # if the admin preview failed to send
```

Add `--yes` to `draft` to skip admin approval and send directly.

## Troubleshooting

**Connection refused error:**
- Ensure PostgreSQL is running: `pg_isready -h localhost -p 5432`
- Check POSTGRES_HOST and POSTGRES_PORT match your Postgres installation

**Authentication failed:**
- Verify POSTGRES_USER and POSTGRES_PASSWORD are correct
- Check PostgreSQL user exists and password is set

**Database does not exist:**
- Create the database: `createdb feedback_bot`
- Or set POSTGRES_DB to an existing database name

