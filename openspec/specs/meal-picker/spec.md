# meal-picker Specification

## Purpose
TBD - created by archiving change add-meal-picker. Update Purpose after archive.
## Requirements
### Requirement: Random meal suggestion command
The system SHALL provide a `/meal` Telegram command that, when invoked, randomly
selects one item from a fixed, non-empty, built-in list of default food/meal
suggestions and replies to the user with that single selection. The command SHALL
be single-turn (a plain command handler, not a multi-step conversation) and SHALL
NOT persist any state about past invocations.

#### Scenario: User requests a meal suggestion
- **WHEN** a user sends `/meal` with no additional arguments
- **THEN** the bot replies with exactly one food/meal name drawn from the built-in
  default list

#### Scenario: Repeated invocations can vary
- **WHEN** a user sends `/meal` multiple times in a row
- **THEN** each reply is independently chosen at random from the built-in default
  list (the bot is not restricted to returning the same item every time, and does
  not require any stored state to do so)

#### Scenario: Extra arguments are ignored
- **WHEN** a user sends `/meal` followed by extra text or arguments (e.g. `/meal now`)
- **THEN** the bot still replies with one random selection from the built-in default
  list and does not treat the extra text as an error or as a custom list

### Requirement: Default meal list is fixed and non-empty
The system SHALL maintain a built-in default list of food/meal suggestions
containing at least 8 distinct items. This list SHALL be a static, in-code
constant in v1 — not sourced from user input, external configuration, or a
database — so that `/meal` always has a valid, non-empty pool to pick from.

#### Scenario: Default list guarantees a valid pick
- **WHEN** the `/meal` command handler runs
- **THEN** the value returned by the random selection is always a member of the
  built-in default list (never empty, `None`, or an out-of-list value)

### Requirement: Command discoverability
The `/meal` command SHALL be registered in the bot's Telegram command suggestion
list and listed in the `/help` reply text, consistent with how other utility
commands (e.g. `/calc`, `/remind`) are surfaced.

#### Scenario: Command appears in Telegram's command suggestions
- **WHEN** a user types `/` in the chat with the bot
- **THEN** `/meal` appears among the suggested commands with a short description
  (e.g. "Randomly pick what to eat today")

#### Scenario: Command appears in /help
- **WHEN** a user sends `/help`
- **THEN** the reply text includes a line describing the `/meal` command and its
  purpose

