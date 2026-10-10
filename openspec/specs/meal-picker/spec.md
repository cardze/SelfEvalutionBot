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
The reply message SHALL carry an inline keyboard with delivery-platform order links
for the selected meal as defined by the "Delivery platform order links" requirement.

#### Scenario: User requests a meal suggestion
- **WHEN** a user sends `/meal` with no additional arguments
- **THEN** the bot replies with exactly one message containing one meal from the
  built-in default meal list, one drink from the built-in default drink list, and a
  deluxe combo name for that pair, with an inline keyboard of order links attached

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
The `/meal` command SHALL be registered in the bot Telegram command suggestion
list and listed in the `/help` reply text, with a description that mentions the meal
and drink combo, consistent with how other utility commands (e.g. `/calc`, `/remind`)
are surfaced. The `/help` line for `/meal` SHALL also mention the Uber Eats and
foodpanda order links. The `/order` command SHALL also be registered in the Telegram
command suggestion list and listed in `/help`, with a description that mentions
finding a named food on Uber Eats and foodpanda.

#### Scenario: Command appears in Telegram command suggestions
- **WHEN** a user types `/` in the chat with the bot
- **THEN** `/meal` appears among the suggested commands with a short description
  mentioning a meal and drink combo (e.g. "Pick a meal + drink combo for today")

#### Scenario: Command appears in /help
- **WHEN** a user sends `/help`
- **THEN** the reply text includes a line describing the `/meal` command as picking a
  meal and drink combo and mentioning Uber Eats and foodpanda links

#### Scenario: Order command is discoverable
- **WHEN** a user types `/` in the chat or sends `/help`
- **THEN** `/order` appears in the command suggestions and in the `/help` text with a
  description mentioning Uber Eats and foodpanda

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

### Requirement: Delivery platform order links
The system SHALL attach to the `/meal` reply an inline keyboard containing exactly two
URL buttons, in order: "Uber Eats" and "foodpanda". Each button URL SHALL be that
platform Taiwan site search URL with the selected meal (not the drink) appended as a
URL-encoded query. The URLs SHALL be built locally from static in-code base URL
constants without any network request, API key, user credential, or stored state. The
bot SHALL NOT place orders, add items to carts, or handle payment on behalf of the user.

#### Scenario: Buttons link to both platforms for the picked meal
- **WHEN** `/meal` selects meal M
- **THEN** the reply inline keyboard has a "Uber Eats" button whose URL starts with
  `https://www.ubereats.com/tw/` and a "foodpanda" button whose URL starts with
  `https://www.foodpanda.com.tw/`, and both URLs contain the URL-encoded form of M

#### Scenario: Meal names with non-ASCII characters are encoded
- **WHEN** the order links are built for a Traditional Chinese meal name such as 牛肉麵
- **THEN** each URL contains the percent-encoded meal (%E7%89%9B%E8%82%89%E9%BA%B5)
  and no raw non-ASCII or space characters

#### Scenario: Drink is not used as the search query
- **WHEN** the order links are built for meal M and drink D
- **THEN** neither URL contains the URL-encoded form of D unless it is also part of M

#### Scenario: No outbound requests
- **WHEN** the `/meal` handler runs
- **THEN** it builds the links without performing any HTTP request

### Requirement: Order links for user-specified food
The system SHALL provide an `/order` Telegram command. When invoked with food text
(e.g. `/order 牛肉麵`), the system SHALL collapse whitespace in the text, strip it, and
truncate it to at most 50 characters. It SHALL then reply with exactly one plain-text
message that names the food, with an inline keyboard of exactly two URL buttons, in
order: "Uber Eats" and "foodpanda". These buttons SHALL be built the same way as the
`/meal` delivery platform order links, using the normalized food text as the search
query. The command SHALL be single-turn and stateless, SHALL NOT perform any network
request, and SHALL NOT place orders, add items to carts, or handle payment.

#### Scenario: User requests order links for a named food
- **WHEN** a user sends `/order 牛肉麵`
- **THEN** the bot replies with one message mentioning 牛肉麵, with an inline keyboard
  whose "Uber Eats" button URL starts with `https://www.ubereats.com/tw/` and whose
  "foodpanda" button URL starts with `https://www.foodpanda.com.tw/`, and both URLs
  contain `%E7%89%9B%E8%82%89%E9%BA%B5`

#### Scenario: Multi-word food text is joined and encoded
- **WHEN** a user sends `/order` with the words `fried` and `chicken` separated by extra spaces
- **THEN** the search query used in both URLs is the encoded form of `fried chicken`
  (single space, trimmed), and the URLs contain no raw space characters

#### Scenario: Overlong food text is truncated
- **WHEN** a user sends `/order` followed by more than 50 characters of text
- **THEN** the query used in the links is the first 50 characters of the normalized text

#### Scenario: Missing food text shows usage
- **WHEN** a user sends `/order` with no text
- **THEN** the bot replies with a usage hint that includes an example such as
  `/order 牛肉麵` and mentions `/meal` for a random pick, and the reply has no inline
  keyboard

#### Scenario: No outbound requests
- **WHEN** the `/order` handler runs
- **THEN** it builds the links without performing any HTTP request

