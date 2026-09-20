## Requirement: Surface command discovery hints
The bot SHALL show an explicit hint in the welcome and help messages that tells users to type `/` to see available command suggestions.

### Scenario: User starts the bot
- **WHEN** a user sends `/start`
- **THEN** the response includes a short explanation of how to discover commands

### Scenario: User requests help
- **WHEN** a user sends `/help`
- **THEN** the response lists the available commands and repeats the discovery hint

### Scenario: Command descriptions stay aligned
- **WHEN** Telegram displays the bot command list
- **THEN** the descriptions match the messages shown in `/start` and `/help`
