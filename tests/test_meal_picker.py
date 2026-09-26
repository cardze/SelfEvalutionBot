"""Tests for the /meal command handler and its default meal list.

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


def test_default_meals_has_at_least_eight_distinct_items():
    assert len(bot.DEFAULT_MEALS) >= 8
    assert len(set(bot.DEFAULT_MEALS)) == len(bot.DEFAULT_MEALS)


def test_meal_picker_replies_with_member_of_default_meals():
    update = _update()
    replies = _run(bot.meal_picker, update, _context())

    assert len(replies) == 1
    assert replies[-1] in bot.DEFAULT_MEALS


def test_meal_picker_only_ever_returns_default_meals_across_many_calls():
    for _ in range(200):
        update = _update()
        replies = _run(bot.meal_picker, update, _context())
        assert replies
        assert replies[-1] is not None
        assert replies[-1] != ""
        assert replies[-1] in bot.DEFAULT_MEALS


def test_meal_picker_uses_random_choice_on_default_meals():
    update = _update()
    with patch("bot.random.choice", wraps=bot.random.choice) as mock_choice:
        replies = _run(bot.meal_picker, update, _context())

    mock_choice.assert_called_once_with(bot.DEFAULT_MEALS)
    assert replies[-1] in bot.DEFAULT_MEALS


def test_meal_picker_ignores_extra_arguments():
    update = _update()
    replies = _run(bot.meal_picker, update, _context(args=["now"]))

    assert len(replies) == 1
    assert replies[-1] in bot.DEFAULT_MEALS


def test_meal_registered_in_setup_bot_commands():
    calls = []

    class RecordingBot:
        async def set_my_commands(self, commands):
            calls.append(commands)

    class RecordingApplication:
        def __init__(self):
            self.bot = RecordingBot()

    asyncio.run(bot.setup_bot_commands(RecordingApplication()))
    names = [c.command for c in calls[0]]
    assert "meal" in names


def test_meal_appears_in_help_text():
    update = FakeUpdate()
    asyncio.run(bot.help_command(update, None))
    message = update.message.replies[-1]

    assert "/meal" in message
    assert "Randomly pick what to eat today" in message
