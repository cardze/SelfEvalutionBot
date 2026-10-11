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


def _start_background_with(set_my_commands, monkeypatch):
    """Run start_background on a live loop with a stubbed reminder loop; return (calls, started)."""
    calls, started = [], []

    async def fake_delivery_loop(_bot):
        started.append(True)

    async def recording_set_my_commands(commands):
        calls.append(commands)
        await set_my_commands()

    monkeypatch.setattr(bot.reminders, "delivery_loop", fake_delivery_loop)
    application = SimpleNamespace(bot=SimpleNamespace(set_my_commands=recording_set_my_commands))

    async def run():
        bot.start_background(application)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run())
    return calls, started


def test_start_background_registers_original_command_menu(monkeypatch):
    async def ok():
        pass

    calls, started = _start_background_with(ok, monkeypatch)
    assert len(calls) == 1
    names = [c.command for c in calls[0]]
    assert "start" in names and "help" in names
    assert started == [True]


def test_start_background_menu_timeout_does_not_stop_reminder_loop(monkeypatch, caplog):
    from telegram.error import TimedOut

    async def timeout():
        raise TimedOut()

    calls, started = _start_background_with(timeout, monkeypatch)
    assert len(calls) == 1 and started == [True]
    assert "command registration failed" in caplog.text
