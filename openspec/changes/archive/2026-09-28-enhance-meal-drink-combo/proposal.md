## Why

User feedback asks that `/meal` not only pick a meal but also recommend a drink to go
with it and give the pairing a fun "deluxe" name. Today `/meal` (capability
`meal-picker`) replies with a single bare dish name from `DEFAULT_MEALS`. A meal + drink
combo with a playful premium-sounding name makes the command more useful and fun.

## What Changes

- `/meal` reply changes from a single dish name to a combo: one random meal, one random
  drink, and a generated deluxe combo name built from both.
- Add a fixed, non-empty built-in drink list (`DEFAULT_DRINKS`, at least 8 items).
- Add fixed, non-empty built-in deluxe name word pools (`DELUXE_PREFIXES`,
  `DELUXE_SUFFIXES`) used to generate the combo name with a simple template.
- Extract combo building into a pure, testable helper (`build_meal_combo(rng)`).
- `/meal` stays single-turn, stateless, dependency-free; extra args remain ignored.
- The `/meal` reply text format changes (multi-line combo instead of only the dish
  name). No API or storage impact.

Assumptions (no clarification was available in this unattended run):
- The drink is chosen independently at random (no meal-to-drink pairing rules).
- The deluxe name is template-generated from static word pools (no LLM or external
  service), in Traditional Chinese to match existing bot copy.
- `/help` and the Telegram command description are updated to mention the drink combo.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `meal-picker`: `/meal` reply now includes a random drink and a generated deluxe combo
  name; adds a built-in drink list and deluxe-name word pools; updated command description.

## Impact

- Code: `bot.py` (new constants, new `build_meal_combo` helper, `meal_picker` handler,
  `setup_bot_commands` description, `help_command` text).
- Tests: `tests/test_meal_picker.py` updated and extended.
- No new dependencies, no DB/schema changes, no runner changes.
