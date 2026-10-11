"""bot.register_handlers adds the same handlers and groups as `python bot.py` always has.

Kept apart from the gateway plugin's tests, which runner-built changes may not touch
(runner/guard.py), because adding a bot command means updating this list.
"""

from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler

import bot


class FakeApplication:
    def __init__(self):
        self.handlers = []  # (handler, group)

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))


def _describe(handler):
    if isinstance(handler, CommandHandler):
        return ("command", tuple(sorted(handler.commands)))
    if isinstance(handler, CallbackQueryHandler):
        return ("callback", handler.pattern.pattern)
    if isinstance(handler, ConversationHandler):
        return ("conversation", tuple(sorted(handler.entry_points[0].commands)))
    if isinstance(handler, MessageHandler):
        return ("message", handler.callback.__name__)
    return ("other", type(handler).__name__)


def test_register_handlers_matches_bot_main():
    app = FakeApplication()
    bot.register_handlers(app)
    got = [(_describe(h), g) for h, g in app.handlers]
    assert got == [
        (("message", "clarification_reply"), -1),
        (("message", "runner_note_reply"), -2),
        (("callback", "^run:"), 0),
        (("callback", "^sig:"), 0),
        (("callback", "^apv:"), 0),
        (("callback", "^clr:"), 0),
        (("command", ("start",)), 0),
        (("command", ("help",)), 0),
        (("command", ("calc",)), 0),
        (("command", ("meal",)), 0),
        (("command", ("remind",)), 0),
        (("command", ("reminders",)), 0),
        (("conversation", ("feedback",)), 0),
    ]


