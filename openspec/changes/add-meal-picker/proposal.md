## Why

A user asked for a "what should I eat today" picker (原文: "我想要一個「今天吃什麼」抽選器").
The bot already offers small self-contained utilities inline in Telegram (e.g. `/calc`,
`/remind`); a random meal/food suggester is a similarly low-effort, high-value addition
that solves decision fatigue around meal choice without leaving the chat.

## What Changes

- Add a `/meal` command that randomly picks one food/meal suggestion from a fixed,
  built-in default list and replies with it.
- Register `/meal` in `setup_bot_commands` (Telegram command suggestions) and in the
  `/help` reply text, following the existing pattern used by `/calc` and `/remind`.
- No new external dependencies: randomness is provided by Python's stdlib `random`
  module (`random.choice`).
- No persistence: each `/meal` invocation is a single-turn, stateless request/response
  with no database read or write.

**Assumptions recorded here since no user is available to clarify (autonomous runner mode):**
- v1 ships with a fixed, hard-coded default list of common food/meal options (mix of
  Taiwanese/common dishes, e.g. 牛肉麵, 滷肉飯, 火鍋, 壽司, 義大利麵, 漢堡, 咖哩飯, 炒飯, 沙拉, 拉麵).
  There is no user-managed or per-user custom list in this version.
- `/meal` takes no arguments in v1. Accepting a custom comma-separated list via command
  arguments is explicitly deferred (see Non-goals in design.md) to keep scope tight and
  match the feedback as literally requested (a picker, not a list-management feature).
- One random pick is returned per invocation; there is no "don't repeat last pick" or
  weighting logic in v1.
- Bot-facing reply text may use Traditional Chinese and/or English; the implementation
  itself (code, identifiers, docs) stays language-agnostic per repo convention.

## Capabilities

### New Capabilities
- `meal-picker`: a single-turn `/meal` Telegram command that randomly selects one item
  from a fixed built-in list of food/meal suggestions and replies with it.

### Modified Capabilities
- (none) — `/meal` is registered in `setup_bot_commands` and `/help` following the same
  pattern already established by `/calc`; this does not change any requirement in the
  existing `command-hints` capability, only adds a new command entry consistent with it.

## Impact

- **Affected code**: `bot.py` only — new handler function, one new `CommandHandler`
  registration, one new `BotCommand` entry, one new line in the `/help` text.
- **Affected tests**: new `tests/test_meal_picker.py`, mirroring `tests/test_calculator.py`
  conventions.
- **Dependencies**: none added (Python stdlib `random` only).
- **Persistence**: none — no schema, storage, or migration changes.
- **Out of scope**: this proposal does not implement or modify code; implementation is a
  later BUILD-stage task for `coder`/`evaluator`.
