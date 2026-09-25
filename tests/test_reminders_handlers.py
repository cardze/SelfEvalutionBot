"""Handler tests for /remind and /reminders using fakes (no DB).

Mirrors tests/test_clarification.py and tests/test_command_hints.py's fake/monkeypatch style.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import bot
from reminders import ReminderService

USER_ID = 777
CHAT_ID = 888


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def _update(args_text=""):
    message = FakeMessage()
    update = SimpleNamespace(
        message=message,
        effective_user=SimpleNamespace(id=USER_ID),
        effective_chat=SimpleNamespace(id=CHAT_ID),
    )
    context = SimpleNamespace(args=args_text.split() if args_text else [])
    return update, context


def _run(handler, update, context):
    asyncio.run(handler(update, context))
    return update.message.replies


def _make_row(user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds):
    return dict(
        id=uuid4(),
        user_id=user_id,
        chat_id=chat_id,
        message_text=message_text,
        next_fire_at=next_fire_at,
        is_recurring=is_recurring,
        interval_seconds=interval_seconds,
        active=True,
    )


@pytest.fixture
def store(monkeypatch):
    """Patch ReminderService with an in-memory recorder."""
    calls = []
    state = dict(rows=[])

    def create_reminder(user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds):
        calls.append(("create", (user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds)))
        row = _make_row(user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds)
        state["rows"].append(row)
        return row

    def list_active(user_id):
        calls.append(("list_active", (user_id,)))
        return [row for row in state["rows"] if row["user_id"] == user_id and row["active"]]

    def cancel(user_id, reminder_id):
        calls.append(("cancel", (user_id, reminder_id)))
        for row in state["rows"]:
            if row["id"] == reminder_id and row["user_id"] == user_id and row["active"]:
                row["active"] = False
                return True
        return False

    monkeypatch.setattr(ReminderService, "create_reminder", staticmethod(create_reminder))
    monkeypatch.setattr(ReminderService, "list_active", staticmethod(list_active))
    monkeypatch.setattr(ReminderService, "cancel", staticmethod(cancel))
    return SimpleNamespace(calls=calls, state=state)


# ---------- /remind ----------


def test_remind_missing_args_shows_usage(store):
    update, context = _update("")
    replies = _run(bot.remind, update, context)
    assert "Usage: /remind" in replies[-1]
    assert store.calls == []


def test_remind_missing_message_shows_usage(store):
    update, context = _update("in 10m")
    replies = _run(bot.remind, update, context)
    assert "Usage: /remind" in replies[-1]
    assert store.calls == []


def test_remind_relative_creates_and_confirms(store):
    update, context = _update("in 10m Take the bread out")
    replies = _run(bot.remind, update, context)
    assert "Reminder scheduled" in replies[-1]
    assert store.calls[0][0] == "create"
    _, (user_id, chat_id, message_text, next_fire_at, is_recurring, interval_seconds) = store.calls[0]
    assert (user_id, chat_id, message_text) == (USER_ID, CHAT_ID, "Take the bread out")
    assert is_recurring is False
    assert interval_seconds is None


def test_remind_absolute_creates_and_confirms(store):
    update, context = _update("at 23:59 Call the dentist")
    replies = _run(bot.remind, update, context)
    assert "Reminder scheduled" in replies[-1]
    _, (_, _, message_text, _, is_recurring, interval_seconds) = store.calls[0]
    assert message_text == "Call the dentist"
    assert is_recurring is False
    assert interval_seconds is None


def test_remind_every_creates_recurring_and_confirms(store):
    update, context = _update("every 1h Drink water")
    replies = _run(bot.remind, update, context)
    assert "Repeating notice scheduled" in replies[-1]
    _, (_, _, message_text, _, is_recurring, interval_seconds) = store.calls[0]
    assert message_text == "Drink water"
    assert is_recurring is True
    assert interval_seconds == 3600


def test_remind_unparseable_time_shows_error(store):
    update, context = _update("sometime soon Water the plants")
    replies = _run(bot.remind, update, context)
    assert "Usage: /remind" in replies[-1]
    assert store.calls == []


def test_remind_interval_below_minimum_shows_minimum_error(store):
    update, context = _update("every 0m Ping me")
    replies = _run(bot.remind, update, context)
    assert "minimum" in replies[-1].lower()
    assert store.calls == []


# ---------- /reminders ----------


def test_reminders_lists_entries(store):
    next_fire_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    row = _make_row(USER_ID, CHAT_ID, "Take the bread out", next_fire_at, False, None)
    store.state["rows"].append(row)

    update, context = _update("")
    replies = _run(bot.reminders_command, update, context)
    assert "Take the bread out" in replies[-1]
    assert str(row["id"]) in replies[-1]


def test_reminders_with_none_says_so(store):
    update, context = _update("")
    replies = _run(bot.reminders_command, update, context)
    assert "no active reminders" in replies[-1].lower()


def test_reminders_cancel_succeeds_for_owner(store):
    next_fire_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    row = _make_row(USER_ID, CHAT_ID, "mine", next_fire_at, False, None)
    store.state["rows"].append(row)

    update, context = _update("cancel " + str(row["id"]))
    replies = _run(bot.reminders_command, update, context)
    assert "cancelled" in replies[-1].lower()
    assert row["active"] is False


def test_reminders_cancel_fails_clearly_for_non_owner(store):
    next_fire_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    row = _make_row(999, 999, "not mine", next_fire_at, False, None)
    store.state["rows"].append(row)

    update, context = _update("cancel " + str(row["id"]))
    replies = _run(bot.reminders_command, update, context)
    assert "no active reminder" in replies[-1].lower()
    assert row["active"] is True  # not mutated


def test_reminders_cancel_fails_clearly_for_unknown_id(store):
    update, context = _update("cancel " + str(uuid4()))
    replies = _run(bot.reminders_command, update, context)
    assert "no active reminder" in replies[-1].lower()


def test_reminders_cancel_invalid_id_shows_error_not_crash(store):
    update, context = _update("cancel not-a-uuid")
    replies = _run(bot.reminders_command, update, context)
    assert "valid reminder id" in replies[-1].lower()
    assert store.calls == []
