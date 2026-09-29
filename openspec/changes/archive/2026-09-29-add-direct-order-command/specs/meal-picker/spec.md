## ADDED Requirements

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

## MODIFIED Requirements

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
