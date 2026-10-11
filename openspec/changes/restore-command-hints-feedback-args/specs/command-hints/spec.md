## ADDED Requirements

### Requirement: Original command menu registered on startup
The bot SHALL register its original command menu (`setup_bot_commands`: `/start`, `/feedback`,
`/calc`, `/meal`, `/remind`, `/reminders`, `/cancel`, `/help` with their descriptions) whenever its
background tasks start, in both the standalone and the gateway run mode. A failed registration
SHALL be logged and SHALL NOT stop startup.

#### Scenario: Background starts
- **WHEN** `start_background(application)` runs on a live event loop
- **THEN** `set_my_commands` is called once with the original command list including `start` and `help`

#### Scenario: Registration fails
- **WHEN** `set_my_commands` raises a Telegram timeout during startup
- **THEN** a warning is logged and the reminder delivery loop still starts
