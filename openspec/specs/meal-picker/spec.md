# meal-picker Specification

## Purpose
TBD - created by archiving change add-meal-picker. Update Purpose after archive.
## Requirements
### Requirement: Random meal suggestion command
The system SHALL provide a `/meal` Telegram command that, when invoked, randomly
selects one meal from the built-in default meal list and one drink from the built-in
default drink list, generates a deluxe combo name for that meal and drink pair, and
replies to the user with a single message containing the deluxe combo name, the meal,
and the drink. The command SHALL be single-turn (a plain command handler, not a
multi-step conversation) and SHALL NOT persist any state about past invocations.

#### Scenario: User requests a meal suggestion
- **WHEN** a user sends `/meal` with no additional arguments
- **THEN** the bot replies with exactly one message containing one meal from the
  built-in default meal list, one drink from the built-in default drink list, and a
  deluxe combo name for that pair

#### Scenario: Repeated invocations can vary
- **WHEN** a user sends `/meal` multiple times in a row
- **THEN** the meal, drink, and deluxe name in each reply are independently chosen at
  random without requiring any stored state

#### Scenario: Extra arguments are ignored
- **WHEN** a user sends `/meal` followed by extra text or arguments (e.g. `/meal now`)
- **THEN** the bot still replies with a random meal and drink combo and deluxe name and
  does not treat the extra text as an error or as a custom list

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
list and listed in the `/help` reply text, with a description that mentions the meal
and drink combo, consistent with how other utility commands (e.g. `/calc`, `/remind`)
are surfaced.

#### Scenario: Command appears in Telegram's command suggestions
- **WHEN** a user types `/` in the chat with the bot
- **THEN** `/meal` appears among the suggested commands with a short description
  mentioning a meal and drink combo (e.g. "Pick a meal + drink combo for today")

#### Scenario: Command appears in /help
- **WHEN** a user sends `/help`
- **THEN** the reply text includes a line describing the `/meal` command as picking a
  meal and drink combo

### Requirement: Default drink list is fixed and non-empty
The system SHALL maintain a built-in default list of drink suggestions containing at
least 8 distinct items, defined as a static in-code constant (not sourced from user
input, external configuration, or a database).

#### Scenario: Drink pick is always valid
- **WHEN** the `/meal` combo is built
- **THEN** the selected drink is always a member of the built-in default drink list
  (never empty, `None`, or an out-of-list value)

### Requirement: Deluxe combo name generation
The system SHALL generate the deluxe combo name locally (no external service) from
static, non-empty built-in word pools combined with the selected meal and drink, such
that the name contains both the selected meal and the selected drink.

#### Scenario: Deluxe name reflects the combination
- **WHEN** the combo is built with meal `M` and drink `D`
- **THEN** the deluxe name is a non-empty string that contains both `M` and `D`

#### Scenario: Deluxe name uses built-in word pools
- **WHEN** the combo is built with a deterministic random source
- **THEN** the deluxe name is composed of one prefix and one suffix drawn from the
  built-in deluxe word pools together with the selected meal and drink

