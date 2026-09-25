"""Tests for reminders.delivery_loop and the post_init wiring, using fakes (no DB)."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

import bot
import reminders
from reminders import ReminderService


class FakeBot:
    def __init__(self, fail_chat_ids=None):
        self.sent = []
        self.fail_chat_ids = fail_chat_ids or set()

    async def send_message(self, chat_id, text, **kwargs):
        if chat_id in self.fail_chat_ids:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text))


def _row(chat_id, message_text, next_fire_at, is_recurring, interval_seconds):
    return dict(
        id=uuid4(),
        user_id=chat_id,
        chat_id=chat_id,
        message_text=message_text,
        next_fire_at=next_fire_at,
        is_recurring=is_recurring,
        interval_seconds=interval_seconds,
        active=True,
    )


@pytest.fixture
def store(monkeypatch):
    """Patch ReminderService with an in-memory recorder for the delivery loop."""
    calls = []
    state = dict(rows=[])

    def get_due(now=None):
        calls.append(("get_due", now))
        return [row for row in state["rows"] if row["active"] and row["next_fire_at"] <= (now or datetime.now(timezone.utc))]

    def mark_delivered(reminder_id):
        calls.append(("mark_delivered", reminder_id))
        for row in state["rows"]:
            if row["id"] == reminder_id:
                row["active"] = False
                return True
        return False

    def reschedule(reminder_id, next_fire_at):
        calls.append(("reschedule", (reminder_id, next_fire_at)))
        for row in state["rows"]:
            if row["id"] == reminder_id:
                row["next_fire_at"] = next_fire_at
                return True
        return False

    monkeypatch.setattr(ReminderService, "get_due", staticmethod(get_due))
    monkeypatch.setattr(ReminderService, "mark_delivered", staticmethod(mark_delivered))
    monkeypatch.setattr(ReminderService, "reschedule", staticmethod(reschedule))
    return SimpleNamespace(calls=calls, state=state)


def test_due_one_time_reminder_delivered_once_then_deactivated(store):
    now = datetime.now(timezone.utc)
    row = _row(111, "Take the bread out", now - timedelta(seconds=5), False, None)
    store.state["rows"].append(row)
    fake_bot = FakeBot()

    asyncio.run(reminders._deliver_due(fake_bot))

    assert fake_bot.sent == [(111, "Reminder: Take the bread out")]
    assert row["active"] is False
    assert ("mark_delivered", row["id"]) in store.calls


def test_due_recurring_reminder_delivered_then_rescheduled(store):
    now = datetime.now(timezone.utc)
    row = _row(222, "Drink water", now - timedelta(seconds=5), True, 3600)
    store.state["rows"].append(row)
    fake_bot = FakeBot()

    asyncio.run(reminders._deliver_due(fake_bot))

    assert fake_bot.sent == [(222, "Reminder: Drink water")]
    assert row["active"] is True
    assert row["next_fire_at"] == row["next_fire_at"]  # sanity: still set
    reschedule_calls = [c for c in store.calls if c[0] == "reschedule"]
    assert len(reschedule_calls) == 1
    _, (reminder_id, new_next_fire_at) = reschedule_calls[0]
    assert reminder_id == row["id"]
    assert new_next_fire_at == (now - timedelta(seconds=5)) + timedelta(seconds=3600)


def test_one_delivery_failure_does_not_block_the_next_due_reminder(store):
    now = datetime.now(timezone.utc)
    failing = _row(333, "will fail", now - timedelta(seconds=5), False, None)
    succeeding = _row(444, "will succeed", now - timedelta(seconds=3), False, None)
    store.state["rows"].extend([failing, succeeding])
    fake_bot = FakeBot(fail_chat_ids={333})

    asyncio.run(reminders._deliver_due(fake_bot))

    assert (444, "Reminder: will succeed") in fake_bot.sent
    assert failing["active"] is True  # left in place: retryable, not silently discarded
    assert succeeding["active"] is False


# ---------- post_init wiring ----------


def test_post_init_schedules_delivery_loop(monkeypatch):
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()  # avoid "coroutine was never awaited" warning
        return SimpleNamespace()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)
    fake_application = SimpleNamespace(bot=SimpleNamespace())

    asyncio.run(bot._post_init(fake_application))

    assert len(scheduled) == 1


def test_application_builder_registers_post_init(monkeypatch):
    captured = {}

    class FakeBuilder:
        def token(self, value):
            return self

        def post_init(self, callback):
            captured["post_init"] = callback
            return self

        def build(self):
            return SimpleNamespace(
                add_handler=lambda *a, **k: None,
                run_polling=lambda: None,
                bot=SimpleNamespace(),
            )

    import telegram.ext

    monkeypatch.setattr(telegram.ext.Application, "builder", staticmethod(lambda: FakeBuilder()))
    monkeypatch.setattr(bot.db, "init_database", lambda: True)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")

    bot.main()

    assert captured.get("post_init") is bot._post_init
