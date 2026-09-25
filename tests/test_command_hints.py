import asyncio
from types import SimpleNamespace

import bot


class FakeMessage:
    def __init__(self):
        self.payloads = []

    async def reply_text(self, text, **kwargs):
        self.payloads.append(text)


class FakeUpdate:
    def __init__(self):
        self.message = FakeMessage()


def test_start_mentions_typing_slash_for_commands():
    update = FakeUpdate()
    asyncio.run(bot.start(update, None))
    message = update.message.payloads[-1]

    assert "type /" in message.lower()
    assert "command" in message.lower()


def test_help_lists_all_commands_and_mentions_slash_hint():
    update = FakeUpdate()
    asyncio.run(bot.help_command(update, None))
    message = update.message.payloads[-1]

    assert "/start" in message
    assert "/help" in message
    assert "/feedback" in message
    assert "/cancel" in message
    assert "/remind" in message
    assert "/reminders" in message
    assert "type /" in message.lower()


def test_setup_bot_commands_registers_remind_and_reminders():
    calls = []

    class RecordingBot:
        async def set_my_commands(self, commands):
            calls.append(commands)

    class RecordingApplication:
        def __init__(self):
            self.bot = RecordingBot()

    asyncio.run(bot.setup_bot_commands(RecordingApplication()))
    names = [c.command for c in calls[0]]
    assert "remind" in names
    assert "reminders" in names


import telegram


class FakeBot:
    def __init__(self):
        self.calls = 0

    async def set_my_commands(self, commands):
        self.calls += 1
        raise telegram.error.TimedOut('timed out')


class FakeApplication:
    def __init__(self):
        self.bot = FakeBot()


def test_setup_bot_commands_ignores_telegram_timeout():
    app = FakeApplication()
    asyncio.run(bot.setup_bot_commands(app))
    assert app.bot.calls == 1
