"""Tests for the /meal command handler, combo helper, and its built-in pools.

Mirrors the async-handler-testing style used in tests/test_command_hints.py
and tests/test_reminders_handlers.py (fake update/message objects plus
asyncio.run(handler(update, context))), since /meal is a stateless handler
rather than a pure function like the calculator.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import bot


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class FakeUpdate:
    def __init__(self):
        self.message = FakeMessage()


def _update():
    return FakeUpdate()


def _context(args=None):
    return SimpleNamespace(args=args or [])


def _run(handler, update, context):
    asyncio.run(handler(update, context))
    return update.message.replies


class FirstChoiceRng:
    """Deterministic rng stub: always picks the first item of the sequence."""

    def choice(self, seq):
        return seq[0]


def _combo_lines(reply):
    lines = reply.split("\n")
    assert len(lines) == 3
    assert lines[0].startswith("✨ ")
    assert lines[1].startswith("🍽 餐點：")
    assert lines[2].startswith("🥤 飲料：")
    return (
        lines[0][len("✨ "):],
        lines[1][len("🍽 餐點："):],
        lines[2][len("🥤 飲料："):],
    )


def _assert_valid_combo(meal, drink, deluxe_name):
    assert meal in bot.DEFAULT_MEALS
    assert drink in bot.DEFAULT_DRINKS
    assert deluxe_name
    assert any(
        deluxe_name == f"{prefix}{meal}佐{drink}{suffix}"
        for prefix in bot.DELUXE_PREFIXES
        for suffix in bot.DELUXE_SUFFIXES
    )


def test_default_meals_has_at_least_eight_distinct_items():
    assert len(bot.DEFAULT_MEALS) >= 8
    assert len(set(bot.DEFAULT_MEALS)) == len(bot.DEFAULT_MEALS)


def test_default_drinks_has_at_least_eight_distinct_items():
    assert len(bot.DEFAULT_DRINKS) >= 8
    assert len(set(bot.DEFAULT_DRINKS)) == len(bot.DEFAULT_DRINKS)
    assert all(drink and "佐" not in drink for drink in bot.DEFAULT_DRINKS)


def test_deluxe_pools_are_non_empty_and_distinct():
    for pool in (bot.DELUXE_PREFIXES, bot.DELUXE_SUFFIXES):
        assert len(pool) >= 4
        assert len(set(pool)) == len(pool)
        assert all(word and "佐" not in word for word in pool)


def test_build_meal_combo_with_deterministic_rng():
    meal, drink, deluxe_name = bot.build_meal_combo(FirstChoiceRng())

    assert meal == bot.DEFAULT_MEALS[0]
    assert drink == bot.DEFAULT_DRINKS[0]
    assert deluxe_name == (
        f"{bot.DELUXE_PREFIXES[0]}{meal}佐{drink}{bot.DELUXE_SUFFIXES[0]}"
    )


def test_build_meal_combo_always_returns_valid_combo():
    for _ in range(200):
        meal, drink, deluxe_name = bot.build_meal_combo()
        _assert_valid_combo(meal, drink, deluxe_name)


def test_meal_picker_replies_once_with_three_line_combo():
    update = _update()
    replies = _run(bot.meal_picker, update, _context())

    assert len(replies) == 1
    deluxe_name, meal, drink = _combo_lines(replies[-1])
    _assert_valid_combo(meal, drink, deluxe_name)


def test_meal_picker_is_deterministic_with_patched_random_choice():
    update = _update()
    with patch("bot.random.choice", side_effect=lambda seq: seq[0]):
        replies = _run(bot.meal_picker, update, _context())

    meal = bot.DEFAULT_MEALS[0]
    drink = bot.DEFAULT_DRINKS[0]
    deluxe_name = f"{bot.DELUXE_PREFIXES[0]}{meal}佐{drink}{bot.DELUXE_SUFFIXES[0]}"
    assert replies == [f"✨ {deluxe_name}\n🍽 餐點：{meal}\n🥤 飲料：{drink}"]


def test_meal_picker_ignores_extra_arguments():
    update = _update()
    replies = _run(bot.meal_picker, update, _context(args=["now"]))

    assert len(replies) == 1
    deluxe_name, meal, drink = _combo_lines(replies[-1])
    _assert_valid_combo(meal, drink, deluxe_name)


def test_meal_registered_in_setup_bot_commands_with_drink_description():
    calls = []

    class RecordingBot:
        async def set_my_commands(self, commands):
            calls.append(commands)

    class RecordingApplication:
        def __init__(self):
            self.bot = RecordingBot()

    asyncio.run(bot.setup_bot_commands(RecordingApplication()))
    meal_commands = [c for c in calls[0] if c.command == "meal"]
    assert len(meal_commands) == 1
    assert "drink" in meal_commands[0].description.lower()


def test_meal_appears_in_help_text_with_drink():
    update = FakeUpdate()
    asyncio.run(bot.help_command(update, None))
    message = update.message.replies[-1]

    meal_lines = [line for line in message.split("\n") if line.startswith("/meal")]
    assert len(meal_lines) == 1
    assert "drink" in meal_lines[0].lower()
