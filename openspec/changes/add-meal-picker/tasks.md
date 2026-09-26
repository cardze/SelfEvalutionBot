## 1. Implementation

- [x] 1.1 Add a `DEFAULT_MEALS` module-level constant to `bot.py`: a tuple/list of at
      least 8 distinct food/meal name strings (fixed, built-in, non-empty)
- [x] 1.2 Add an `async def meal_picker(update, context)` handler in `bot.py` that calls
      `random.choice(DEFAULT_MEALS)` and replies with the result via
      `update.message.reply_text(...)`; ignore any `context.args` (no error on extra args)
- [x] 1.3 Register `CommandHandler("meal", meal_picker)` in `main()` alongside the other
      command handlers (near `calc`/`remind`)
- [x] 1.4 Add `BotCommand("meal", "Randomly pick what to eat today")` to
      `setup_bot_commands`
- [x] 1.5 Add a `/meal` line to the `/help` reply text in `help_command`, grouped near
      the other utility commands (e.g. after `/calc`, before `/remind`)

## 2. Tests

- [x] 2.1 Create `tests/test_meal_picker.py` mirroring the structure and conventions of
      `tests/test_calculator.py`
- [x] 2.2 Test: `/meal` with no args replies with a value that is a member of
      `DEFAULT_MEALS`
- [x] 2.3 Test: calling the handler repeatedly (e.g. patching `random.choice` or running
      many iterations) only ever returns values from `DEFAULT_MEALS`, verifying the
      random-selection contract (never empty/`None`/out-of-list)
- [x] 2.4 Test: `/meal` with extra arguments (e.g. `/meal now`) still replies with a
      valid `DEFAULT_MEALS` member and does not raise or return an error message
- [x] 2.5 Test: `DEFAULT_MEALS` itself is non-empty and has at least 8 distinct items
      (guards against accidental future edits shrinking the list below spec)

## 3. Documentation / registration checks

- [x] 3.1 Verify `/meal` appears in `setup_bot_commands` and in the `/help` text by
      inspection or a lightweight assertion test (consistent with how `/calc` and
      `/remind` are covered)
