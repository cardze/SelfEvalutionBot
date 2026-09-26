## Context

The bot (`bot.py`) already implements several single-turn, stateless commands using
`python-telegram-bot`'s `CommandHandler` (`/calc`, `/remind`, `/reminders`), registered
both as a `CommandHandler` in `main()` and as a `BotCommand` in `setup_bot_commands`, with
matching text in `help_command`. `/calc` (see `openspec/specs/calculator/spec.md` and its
archived change `openspec/changes/archive/2026-09-20-add-calculator/`) is the closest prior
art: a small, dependency-free, single-turn command with no persistence.

A user requested a "what to eat today" picker. This is a brand-new capability
(`meal-picker`) — no existing spec covers food/meal suggestions.

## Goals / Non-Goals

**Goals:**
- Provide a `/meal` command that, with no arguments, replies with one randomly chosen
  food/meal suggestion from a fixed, built-in default list.
- Keep the feature self-contained: no new dependencies, no persistence, no conversation
  state (plain `CommandHandler`, not a `ConversationHandler`).
- Follow the existing command registration pattern exactly (`setup_bot_commands`,
  `/help` text, `CommandHandler` registration in `main()`).

**Non-Goals (v1):**
- No user-supplied or per-user custom food list (e.g. no `/meal <comma,separated,list>`
  argument parsing). Deferred to a future change if requested again.
- No persistence of past picks, no "avoid repeating the last N picks" logic.
- No weighting/probability customization per item — uniform random choice.
- No multi-turn flow or admin-managed list editing.
- No localization framework — reply text may mix Traditional Chinese and English inline,
  consistent with existing bot copy (e.g. `/remind` usage text).

## Decisions

- **Command name & syntax**: `/meal` with no arguments. Any extra `context.args` are
  ignored in v1 (do not error — simplest, most forgiving behavior, consistent with how
  `/calc` treats missing args as a distinct usage-hint case rather than a hard error).
  Alternative considered: requiring/accepting a custom list via args — rejected for v1
  to keep the change small and directly match the literal feedback ("a picker"), not a
  list-management feature; can be a follow-up change if requested.
- **Randomness source**: Python stdlib `random.choice(DEFAULT_MEALS)`. No new dependency.
  Alternative considered: `random.randint` + manual indexing — `random.choice` is simpler
  and idiomatic.
- **Default list**: a module-level constant (e.g. `DEFAULT_MEALS`) in `bot.py`, a
  non-empty tuple/list of at least 8 short food/meal name strings (mix of Traditional
  Chinese dish names, since the feedback and target audience are Chinese-speaking).
  Alternative considered: loading the list from a config file or DB — rejected for v1
  as unnecessary complexity for a static list; a hard-coded constant is easiest to test
  and matches the "no persistence" goal.
- **Handler shape**: plain `async def meal_picker(update, context)` using
  `update.message.reply_text(...)`, mirroring `calc`'s structure. No `context.args`
  validation needed since args are ignored.
- **Registration**: add to `setup_bot_commands`:
  `BotCommand("meal", "Randomly pick what to eat today")`
  and to `main()`: `application.add_handler(CommandHandler("meal", meal_picker))`.
- **Help text**: add one line to `help_command`'s reply, e.g.
  `"/meal - Randomly pick what to eat today\n"`, placed alongside the other utility
  commands (after `/calc`, before `/remind`) to keep related "utility" commands grouped.

## Risks / Trade-offs

- [Risk] Fixed list may not suit every user's taste/dietary needs → Mitigation: out of
  scope for v1 by design; documented as a known limitation, and a future change could
  add per-user custom lists if feedback asks for it again.
- [Risk] Hard-coded list requires a code change (not just data) to update → Mitigation:
  acceptable trade-off for v1 simplicity; list lives as a single well-named constant so
  it is trivial to extend later.
- [Risk] Test flakiness from randomness → Mitigation: tests assert the picked result is
  a member of `DEFAULT_MEALS` (or use `unittest.mock.patch("random.choice", ...)` /
  seeded calls) rather than asserting an exact value; mirrors how randomness would be
  tested in `tests/test_calculator.py`-style deterministic assertions.

## Migration Plan

N/A — additive only, no data migration. Deploying is just shipping the updated `bot.py`;
rollback is reverting that commit. No backward-compatibility concerns since this is a
brand-new command.

## Open Questions

- None blocking. Should real user feedback later request a custom/user-managed list or
  category filters (e.g. "breakfast" vs "dinner"), that would be scoped as a separate
  follow-up change building on this `meal-picker` capability.
