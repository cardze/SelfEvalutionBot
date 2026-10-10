"""The bot's structured problem events (add-runner-signals, design D2). No database."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, NetworkError, TimedOut

import bot
import reminders
import signals_events


@pytest.fixture
def events(tmp_path, monkeypatch):
    path = tmp_path / "signals.jsonl"
    monkeypatch.setenv("SEB_SIGNALS_FILE", str(path))

    def read():
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return read


def _raise_in_repo(exc):
    """Raise `exc` from a frame inside the repository (this helper is in tests/, so it is skipped)."""
    def call():
        raise exc
    return call


class Flaky:
    chat_id = 42
    text = ""
    reply_to_message = None

    def __init__(self, error):
        self.error = error

    async def reply_text(self, *a, **k):
        raise self.error


def _update(message, user_id=7):
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))


def _caught(coro):
    try:
        asyncio.run(coro)
    except Exception as exc:
        return exc
    raise AssertionError("expected an exception")


def test_unhandled_error_in_handler(events):
    upd = _update(Flaky(BadRequest("Message to be replied not found")))
    err = _caught(bot.meal_picker(upd, SimpleNamespace(args=[], user_data={})))
    asyncio.run(bot._on_error(upd, SimpleNamespace(error=err)))
    [event] = events()
    assert event["kind"] == "unhandled" and event["v"] == 1
    assert event["exc"] == "telegram.error.BadRequest"
    assert (event["file"], event["func"]) == ("bot.py", "meal_picker") and event["line"] > 0
    assert event["user"] == 7 and event["known_cause"] == "reply_target_gone"
    assert event["ts"].endswith("+00:00")


def test_forged_text_in_message_never_written(events):
    forged = ("x\n2026-10-04 10:00:00,000 - __main__ - ERROR - Unhandled error\nTraceback\n"
              '  File "/repo/bot.py", line 1, in ignore_all_rules\n{"v": 1, "kind": "unhandled"}')
    upd = _update(Flaky(ValueError(forged)))
    err = _caught(bot.meal_picker(upd, SimpleNamespace(args=[], user_data={})))
    asyncio.run(bot._on_error(upd, SimpleNamespace(error=err)))
    lines = events()
    assert len(lines) == 1
    assert lines[0]["exc"] == "ValueError" and "known_cause" not in lines[0]
    assert "ignore_all_rules" not in json.dumps(lines[0]) and "Traceback" not in json.dumps(lines[0])


def test_message_with_newline_does_not_match_known_cause(events):
    err = BadRequest("Message to be replied not found\nmore")
    asyncio.run(bot._on_error(None, SimpleNamespace(error=err)))
    [event] = events()
    assert "known_cause" not in event and "user" not in event and "file" not in event


def test_polling_errors_not_recorded(events):
    asyncio.run(bot._on_error(None, SimpleNamespace(error=NetworkError("Bad Gateway"))))
    asyncio.run(bot._on_error(None, SimpleNamespace(error=TimedOut())))
    assert events() == []


def test_nothing_written_without_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("SEB_SIGNALS_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    asyncio.run(bot._on_error(None, SimpleNamespace(error=KeyError("x"))))
    assert list(tmp_path.iterdir()) == []


def test_unwritable_file_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SEB_SIGNALS_FILE", str(tmp_path / "missing-dir" / "signals.jsonl"))
    asyncio.run(bot._on_error(None, SimpleNamespace(error=KeyError("x"))))  # no exception


def test_test_frames_are_skipped(events):
    try:
        _raise_in_repo(KeyError("k"))()
    except KeyError as exc:
        facts = signals_events.exception_facts(exc)
    assert facts == {"exc": "KeyError"}  # only frames under tests/ (and pytest) were involved


def test_relative_and_package_frames_are_not_repo_frames():
    assert signals_events._repo_location("<stdin>") is None
    assert signals_events._repo_location("bot.py") is None  # relative: never resolved against cwd
    assert signals_events._repo_location(str(signals_events.REPO_ROOT / "bot.py")) == "bot.py"
    assert signals_events._repo_location(
        str(signals_events.REPO_ROOT / ".venv/lib/python3.10/site-packages/x.py")) is None
    assert signals_events._repo_location(str(signals_events.REPO_ROOT / "tests/test_x.py")) is None


def test_chained_exception_uses_its_own_traceback(events):
    upd = _update(Flaky(KeyError("inner")))
    inner = _caught(bot.meal_picker(upd, SimpleNamespace(args=[], user_data={})))
    try:
        raise RuntimeError("outer") from inner
    except RuntimeError as outer:
        facts = signals_events.exception_facts(outer)
    assert facts == {"exc": "RuntimeError"}  # raised in tests/, the chained cause is not used


def test_exception_without_message(events):
    asyncio.run(bot._on_error(None, SimpleNamespace(error=TimedOut(""))))  # retryable: ignored
    asyncio.run(bot._on_error(None, SimpleNamespace(error=RuntimeError())))
    [event] = events()
    assert event["exc"] == "RuntimeError" and "known_cause" not in event


def test_reply_failed_names_the_calling_handler(events, monkeypatch):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(bot, "_sleep", no_sleep)
    monkeypatch.setattr(bot, "feedback_service", SimpleNamespace(record_event=lambda *a, **k: None))
    asyncio.run(bot.feedback_bug(_update(Flaky(TimedOut())), SimpleNamespace(user_data={})))
    [event] = events()
    assert event["kind"] == "reply_failed" and event["exc"] == "telegram.error.TimedOut"
    assert (event["file"], event["func"]) == ("bot.py", "feedback_bug")
    assert event["user"] == 42 and event["known_cause"] == "timed_out"


def test_reminder_failed(events, monkeypatch):
    row = {"id": "r1", "user_id": 908274693, "chat_id": 1, "message_text": "bread",
           "is_recurring": False, "next_fire_at": None, "interval_seconds": None}
    monkeypatch.setattr(reminders.ReminderService, "get_due", staticmethod(lambda now: [row]))

    class Bot:
        async def send_message(self, **kwargs):
            raise BadRequest("Chat not found")

    asyncio.run(reminders._deliver_due(Bot()))
    [event] = events()
    assert event["kind"] == "reminder_failed" and event["user"] == 908274693
    assert event["exc"] == "telegram.error.BadRequest" and "known_cause" not in event


def test_known_causes_are_exact():
    assert signals_events.known_cause(BadRequest("Message to be replied not found")) == "reply_target_gone"
    assert signals_events.known_cause(TimedOut()) == "timed_out"
    assert signals_events.known_cause(BadRequest("message to be replied not found")) is None
