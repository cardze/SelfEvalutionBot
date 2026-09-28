## MODIFIED Requirements

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

### Requirement: Command discoverability
The `/meal` command SHALL be registered in the bot Telegram command suggestion
list and listed in the `/help` reply text, with a description that mentions the meal
and drink combo, consistent with how other utility commands (e.g. `/calc`, `/remind`)
are surfaced. The `/help` line for `/meal` SHALL also mention the Uber Eats and
foodpanda order links.

#### Scenario: Command appears in Telegram command suggestions
- **WHEN** a user types `/` in the chat with the bot
- **THEN** `/meal` appears among the suggested commands with a short description
  mentioning a meal and drink combo (e.g. "Pick a meal + drink combo for today")

#### Scenario: Command appears in /help
- **WHEN** a user sends `/help`
- **THEN** the reply text includes a line describing the `/meal` command as picking a
  meal and drink combo and mentioning Uber Eats and foodpanda links

## ADDED Requirements

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
