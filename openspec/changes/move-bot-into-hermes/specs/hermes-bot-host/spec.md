## ADDED Requirements

### Requirement: Bot commands served by the Hermes gateway
When the `seb` plugin is loaded in a Hermes gateway connected to Telegram, the gateway SHALL handle
`/start`, `/help`, `/feedback`, `/cancel`, `/calc`, `/meal`, `/remind`, `/reminders`, the
clarification buttons and replies, and the runner decision buttons and notes with the same handler
code as `bot.py`, for any Telegram user, before Hermes's own handlers see the update.

#### Scenario: Public user gives feedback
- **WHEN** a user who is not on the owner allowlist sends `/feedback`, then the two answers
- **THEN** the submission is stored exactly as under `bot.py` and neither answer reaches the Hermes agent

#### Scenario: Free text from a public user
- **WHEN** a user who is not on the owner allowlist sends plain text outside a feedback conversation
- **THEN** Hermes declines with a message pointing to the bot's commands, and no agent turn runs

#### Scenario: Owner chats with the agent
- **WHEN** the admin sends plain text outside a feedback conversation
- **THEN** the Hermes agent answers

### Requirement: Background work starts with the gateway
When the plugin is wired to Telegram it SHALL initialize the database schema and start the reminder
delivery loop on the gateway's event loop. A failure SHALL be logged without stopping the gateway.

#### Scenario: Reminder delivery under Hermes
- **WHEN** a reminder becomes due while the bot runs inside the Hermes gateway
- **THEN** it is delivered by the same loop and timing as under `bot.py`

### Requirement: Owner-only data tools
The plugin SHALL give the Hermes agent read-only tools for the actionable feedback queue and the
runner's in-flight run. On a messaging surface each tool SHALL answer only when the
gateway-reported sender id equals `ADMIN_USER_ID`, and SHALL return an error otherwise or when the
sender cannot be determined.

#### Scenario: Owner asks for pending feedback
- **WHEN** the admin asks the agent in Telegram what feedback is pending
- **THEN** the agent can call `seb_feedback_queue` and receives the actionable items

#### Scenario: Identity unavailable
- **WHEN** a tool is called on a messaging surface and no sender id is available
- **THEN** the tool returns an error and no data

### Requirement: Runner scheduled by Hermes cron
`hermes_profile/setup.sh cron` SHALL create one script-only cron job in the `seb` profile that runs the
runner tick hourly without an LLM call and delivers nothing, replacing the launchd runner job.

#### Scenario: Hourly tick
- **WHEN** an hour passes with the host gateway serving the `seb` profile
- **THEN** one runner tick runs with the same lock and log as under launchd

### Requirement: Restart the gateway after a merge
With `BOT_SERVICE=hermes`, after the runner records a merge it SHALL have Hermes's package
manager install the merged requirements (as the plugin's dependencies, without `python-telegram-bot`)
instead of pip-installing into Hermes's interpreter, and SHALL restart the
host gateway (which serves the `seb` profile) from a detached process only after the run is marked merged and the admin is notified.

#### Scenario: Merge from inside the gateway's cron
- **WHEN** a ✅ Merge is processed by a tick that runs inside the gateway's cron
- **THEN** the run is marked `merged`, the admin is told, and then the gateway restarts with the merged code

#### Scenario: Requirements pin an older PTB
- **WHEN** `requirements.txt` contains `python-telegram-bot==20.7`
- **THEN** the plugin's generated dependencies leave that line out

### Requirement: launchd mode stays available
`python bot.py` SHALL keep working with the same handlers, and `BOT_SERVICE` SHALL default to
`launchd`, so the existing supervision and rollback continue to work.

#### Scenario: Rollback
- **WHEN** the admin runs `hermes_profile/setup.sh uninstall` and `runner/setup.sh install-agents`
- **THEN** the bot and runner run under launchd as before
