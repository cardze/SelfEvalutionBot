## 1. Data and helper

- [x] 1.1 Add `DEFAULT_DRINKS` tuple (at least 8 distinct Traditional Chinese drink names) to `bot.py` near `DEFAULT_MEALS`
- [x] 1.2 Add `DELUXE_PREFIXES` and `DELUXE_SUFFIXES` tuples (at least 4 items each)
- [x] 1.3 Add pure helper `build_meal_combo(rng=random)` returning `(meal, drink, deluxe_name)` using template `f"{prefix}{meal}佐{drink}{suffix}"`

## 2. Handler and discoverability

- [x] 2.1 Update `meal_picker` to send one three-line reply (`✨ {deluxe_name}`, `🍽 餐點：{meal}`, `🥤 飲料：{drink}`), still ignoring extra args
- [x] 2.2 Update `BotCommand("meal", ...)` description to "Pick a meal + drink combo for today"
- [x] 2.3 Update the `/help` `/meal` line to mention the meal + drink combo

## 3. Tests

- [x] 3.1 Test `DEFAULT_DRINKS` has at least 8 distinct items and deluxe pools are non-empty
- [x] 3.2 Test `build_meal_combo` with a fake/seeded rng: meal in `DEFAULT_MEALS`, drink in `DEFAULT_DRINKS`, deluxe name contains the meal, the drink, and a prefix/suffix from the pools
- [x] 3.3 Update handler tests: `/meal` sends exactly one reply containing a valid meal, a valid drink, and the deluxe name; extra args still produce a combo
- [x] 3.4 Test `/help` text and bot command description mention the drink combo
- [x] 3.5 Run the full test suite (`pytest`) and confirm all tests pass
