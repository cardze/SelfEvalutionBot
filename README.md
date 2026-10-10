# SelfEvaluationBot

A Telegram bot that evolves by users' feedback.

## Features

- `/start` — Welcome message.
- `/feedback` — Two-step feedback form:
  1. **What bug or current feature didn't meet your expectation.**
  2. **The way you suggest to fix the bug or create a new feature.**
- `/cancel` — Cancel an in-progress feedback session.
- `/remind` / `/reminders` — Schedule a one-time reminder or a repeating notice; see below.

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

## Reminders and Notices

`/remind` lets a user schedule a one-time reminder for a specific future time, or a
repeating notice on a fixed interval. `/reminders` lists and cancels them.

```
/remind in 10m Take the bread out      # one-time, 10 minutes from now
/remind in 2h Check the oven           # one-time, 2 hours from now
/remind in 3d Renew the passport       # one-time, 3 days from now
/remind at 14:30 Call the dentist      # one-time, today if 14:30 hasn't passed, else tomorrow
/remind every 1h Drink water           # repeating, every hour until cancelled
/remind every 30m Stretch              # repeating, every 30 minutes
/remind every 1d Log your mood         # repeating, once a day

/reminders                             # list your active reminders and notices
/reminders cancel <id>                 # cancel one you own (id shown by /reminders)
```

Accepted `<when>` forms: `in <n>m|h|d` (relative one-time), `at HH:MM` (absolute
one-time, 24-hour clock), `every <n>m|h|d` (repeating). Units are `m` (minutes),
`h` (hours), `d` (days).

- **Timezone**: all reminder times are interpreted and stored in **UTC**, not the
  host's local time or the submitter's timezone. This is a known limitation for
  this first version (see `openspec/changes/add-reminder-notifications/design.md`).
- **Minimum repeat interval**: repeating notices must be at least **60 seconds**
  apart; shorter intervals are rejected with an error at creation time.
- **Delivery**: a background loop polls for due reminders roughly every 30 seconds,
  so delivery can be up to ~30 seconds after the scheduled time, not to-the-second.
- One-time reminders fire once and are then marked inactive. Repeating notices keep
  firing at their interval until cancelled via `/reminders cancel <id>`.

## Autonomous Feedback Runner

`runner/` plans and implements **the admin's own feedback** unattended. Nothing reaches `main` without
the admin tapping ✅ in Telegram.

```
launchd (hourly) ─▶ runner/run.sh
   ├─ pending ✅/❌/💬?  → merge / reject / rebuild          (checked every hour)
   └─ new admin feedback? (at most every 5h)
        ├─ clone ~/github/SEB-<id> (branch auto/<id>)
        ├─ self-test: sandbox must block secrets, writes, network   (fails closed)
        ├─ PLAN agent  → OpenSpec change        → 📋 notice
        ├─ BUILD agent → code + tests           → sandboxed pytest
        └─ 🔀 merge request  [✅ Merge] [❌ Reject] [💬 Changes]
✅ → merge into main, archive + sync specs, resolve feedback, pip install, restart bot
```

Agents run with `claude -p` under `runner/settings.template.json`: no access to the main checkout,
`~/.seb-runner` (token), `~/.ssh`; network limited to PyPI; commands cannot escape the sandbox. The
agent has **no database access** (the local Postgres uses `trust` auth, so any access would be an escape):
database tests skip in the sandbox and run in full against a throwaway database after ✅, before merging.
The runner itself never executes unapproved agent-written code or git config outside the sandbox.

### Setup (once)

```bash
runner/setup.sh store-token        # after `claude setup-token`, copy the token, then run this (never paste it)
runner/setup.sh selftest           # must print SELFTEST PASSED
runner/setup.sh install-agents     # stop any hand-started bot.py first; the bot now runs under launchd
```

Optional overrides live in `~/.seb-runner/config.env` (e.g. `THROTTLE_HOURS`, `BUILD_BUDGET_USD`,
`PLAN_TIMEOUT_S`). Logs: `~/.seb-runner/logs/` (`runner.log`, `bot.out.log`, `bot.err.log`).

### Hermes Agent backend

The runner can run every agent step on [Hermes Agent](https://github.com/NousResearch/hermes-agent)
(Nous Research) instead of Claude Code. Set it in `~/.seb-runner/config.env` with
`AGENT_BACKEND=hermes`; without that line the runner keeps using Claude Code.

```
runner tick ─▶ hermes chat --query-file - --format stream-json   (HERMES_HOME=~/.hermes/profiles/seb-runner)
                 ├─ skills: main's .claude/agents + .claude/skills, exported as seb-agent-* / seb-*
                 ├─ tools: terminal, file, todo, delegation   (no memory, skills, web, browser)
                 └─ every tool call ─▶ fresh Docker container, only the workspace at /workspace
                                         └─ internal network ─▶ seb-runner-egress (Squid) ─▶ PyPI only
```

Setup (once, Docker Desktop must be running):

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash   # install Hermes
runner/setup.sh hermes-profile       # create + render the seb-runner profile
HERMES_HOME=~/.hermes/profiles/seb-runner hermes auth add <provider>  # or put the API key in that profile's .env
runner/setup.sh hermes-sandbox       # sandbox image, internal network, PyPI-only egress proxy
runner/setup.sh use-backend hermes
runner/setup.sh selftest             # must print SELFTEST PASSED
```

Optional `config.env` keys: `HERMES_PROVIDER`, `HERMES_MODEL`, `HERMES_SELFTEST_MODEL`, `HERMES_BIN`,
`HERMES_HOME`. The runner re-renders the profile's `config.yaml` from
`runner/hermes/config.template.json` on every tick and refuses to run if it is not isolated, so edit the
template, not the rendered file. Provider keys stay in the profile on the host; they never enter the
sandbox.

- **Management page:** `hermes dashboard` opens the Hermes web UI at http://127.0.0.1:9119. Pick the
  `seb-runner` profile in the sidebar to inspect the runner profile's config, skills and logs.
- **Cost:** Hermes has no per-run dollar cap; runs are bounded by `*_MAX_TURNS` and `*_TIMEOUT_S`.
  Set a spend limit with your provider.
- **Rollback:** `runner/setup.sh use-backend claude`.

### Checking the self-test catches mistakes

To confirm the self-test detects a broken rule, edit `~/.seb-runner/runner-settings.json`, run
`python -m runner.selftest` (expect `SELFTEST FAILED`), then restore it with
`runner/setup.sh render-settings`. **Only do this while the runner is stopped**
(`launchctl bootout gui/$(id -u)/com.seb.runner`) — a running agent uses the same settings file.

### Reviewing a merge request

The 🔀 message includes a command like `git -C <main> diff main...refs/runner/<id>` — the branch is
already fetched into the main checkout for review.

### Cost

Idle hours start no Claude session. A real run costs one self-test (~$0.05), the PLAN and BUILD runs
(capped by `PLAN_BUDGET_USD` / `BUILD_BUDGET_USD`, defaults $2 / $8) and one sandboxed test run (~$0.05).

### Rollback

```bash
runner/setup.sh uninstall-agents   # then start bot.py by hand again
```

## Run the bot on Hermes

The whole bot can run inside a [Hermes Agent](https://github.com/NousResearch/hermes-agent) Telegram
gateway instead of `python bot.py` under launchd. Users see the same bot: `/feedback`, `/remind`,
`/reminders`, `/meal`, `/calc`, clarification questions and reminder delivery are the bot's own
handlers, wired into the gateway by the `seb` plugin ahead of Hermes's handlers. What is new:

- **The owner can chat with the bot.** Any other message from the admin (`ADMIN_USER_ID`) goes to a
  Hermes agent with two read-only tools, `seb_feedback_queue` and `seb_runner_status`, so you can ask
  "what feedback is waiting?" or "what is the runner doing?". Everyone else gets a short note
  pointing to the commands; they cannot talk to the agent or use its tools.
- **The feedback loop runs on Hermes cron.** A script-only job (`seb-runner`, hourly, no model call)
  starts `runner/run.sh` instead of launchd `com.seb.runner`. After you tap ✅ Merge, the runner
  has Hermes install new requirements as the plugin's dependencies (never touching its
  `python-telegram-bot`) and
  restarts the gateway once the merge is recorded.

```
Telegram ─▶ Hermes gateway (profile seb)
              ├─ seb plugin ─▶ bot.register_handlers: /feedback /remind /meal /calc, run:/sig:/apv:/clr: buttons
              │                bot.start_background: reminder delivery
              ├─ owner's other messages ─▶ Hermes agent + seb_feedback_queue / seb_runner_status
              └─ cron seb-runner (hourly) ─▶ runner/run.sh ─▶ PLAN ▸ BUILD ▸ 🔀 merge request
```

Setup (on the Mac that runs the bot, after the runner setup above):

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash   # if Hermes is not installed yet
hermes_profile/setup.sh install   # profile `seb`: plugin, SOUL.md, secrets from .env, owner-only chat
hermes -p seb model               # pick the model for the owner's chats
hermes_profile/setup.sh cron      # hourly runner job in Hermes cron; unloads launchd com.seb.runner
hermes_profile/setup.sh start     # unloads launchd com.seb.bot, restarts the host gateway so it serves `seb`
```

`setup.sh cron` writes `BOT_SERVICE=hermes`, `HERMES_PROFILE`, `HERMES_GATEWAY_PROFILE` and `HERMES_BIN` into
`~/.seb-runner/config.env`. Hermes runs one gateway per machine (started from the `default` profile)
that serves every profile, so `start` and `restart` restart that host gateway; your other profiles
reconnect with it. Restart it by hand with `hermes_profile/setup.sh restart`.

- **Management page:** `hermes dashboard` opens http://127.0.0.1:9119. Pick the `seb` profile in the
  sidebar to see the gateway, the `seb-runner` cron job, the plugin, sessions and logs.
- **Rollback:** `hermes_profile/setup.sh uninstall`, then `runner/setup.sh install-agents` to bring
  back launchd `com.seb.bot` and `com.seb.runner`. `python bot.py` still works on its own.

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

