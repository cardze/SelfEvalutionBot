## Context

`/meal` exists in `bot.py`: a `DEFAULT_MEALS` tuple and a `meal_picker` handler calling
`random.choice(DEFAULT_MEALS)`, registered in `setup_bot_commands`, `/help`, and
`main()`. Tests live in `tests/test_meal_picker.py` using fake update/message objects.
Feedback asks for a recommended drink and a "deluxe" name for the meal + drink combo.

## Goals / Non-Goals

**Goals:**
- `/meal` replies with meal + drink + deluxe combo name in one message.
- Keep it stateless, single-turn, no new dependencies, deterministic to test.

**Non-Goals:**
- Meal-specific drink pairing rules, user-custom lists, AI-generated names,
  persistence, or new commands/flags (no separate `/drink`).

## Decisions

- **Drink list**: module-level `DEFAULT_DRINKS` tuple, at least 8 distinct Traditional
  Chinese drink names (e.g. 珍珠奶茶, 冬瓜茶, 美式咖啡, 檸檬紅茶, 可樂, 豆漿, 綠茶,
  柳橙汁), chosen independently via `rng.choice`. A per-meal pairing map was rejected as
  more maintenance with little value for a random picker.
- **Deluxe name**: template `f"{prefix}{meal}佐{drink}{suffix}"`, with `prefix` from
  `DELUXE_PREFIXES` (e.g. 皇家, 至尊, 黃金, 帝王, 米其林級) and `suffix` from
  `DELUXE_SUFFIXES` (e.g. 豪華套餐, 饗宴, 尊爵組合, 限定套餐); each pool has at least
  4 items. Embedding the meal and drink guarantees the name reflects the combination.
  LLM-generated names were rejected (external dependency, cost, non-determinism).
- **Pure helper**: `build_meal_combo(rng=random)` returns `(meal, drink, deluxe_name)`.
  Accepting any object with `.choice` makes tests deterministic without patching globals.
- **Reply format** (three lines): `✨ {deluxe_name}`, then `🍽 餐點：{meal}`, then
  `🥤 飲料：{drink}`.
- **Discoverability**: BotCommand description becomes "Pick a meal + drink combo for
  today"; the `/help` line is updated similarly.

## Risks / Trade-offs

- [Odd combos such as 火鍋 + 可樂] → Acceptable; it is a playful random picker.
- [Existing tests assert the reply is a single meal] → Update tests to the new format.
- [Randomness in tests] → Inject a fake rng or assert membership in the pools.

## Migration Plan

Additive code change in `bot.py`; rollback is reverting the commit. No data migration.

## Open Questions

- None blocking. If users later want sensible pairings, add a meal-to-drinks map in a
  follow-up change.
