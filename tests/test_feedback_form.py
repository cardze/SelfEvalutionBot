"""Tests for the /feedback form's resilience to Telegram send failures (harden-feedback-conversation).

No database: bot.feedback_service and FeedbackService lookups are stubbed, and bot._sleep records
the waits instead of sleeping.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
from telegram.ext import ApplicationHandlerStop, ConversationHandler

import bot


class FlakyMessage:
    """A message whose reply_text raises the given errors, in order, before succeeding."""

    def __init__(self, text="", errors=(), reply_to=None):
        self.text = text
        self.errors = list(errors)
        self.attempts = []
        self.reply_to_message = reply_to

    async def reply_text(self, text, **kwargs):
        self.attempts.append(text)
        if self.errors:
            raise self.errors.pop(0)


class FakeService:
    def __init__(self, store_error=None):
        self.stored = []
        self.events = []
        self.store_error = store_error

    def record_event(self, user_id, event_type, submission_id=None):
        self.events.append(event_type)

    def store_submission(self, user_id, bug, suggestion):
        if self.store_error:
            raise self.store_error
        self.stored.append((bug, suggestion))
        return "sub-1"


@pytest.fixture
def waits(monkeypatch):
    recorded = []

    async def fake_sleep(seconds):
        recorded.append(seconds)

    monkeypatch.setattr(bot, "_sleep", fake_sleep)
    return recorded


@pytest.fixture
def service(monkeypatch):
    fake = FakeService()
    monkeypatch.setattr(bot, "feedback_service", fake)
    return fake


def _update(message, user_id=42):
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=user_id))


def _context(**user_data):
    return SimpleNamespace(user_data=dict(user_data), args=[])


def _timeouts(n):
    return [TimedOut() for _ in range(n)]


# ---------- _reply ----------


def test_reply_succeeds_first_time(waits):
    message = FlakyMessage()
    assert asyncio.run(bot._reply(message, "hi")) is True
    assert message.attempts == ["hi"] and waits == []


def test_reply_retries_one_timeout(waits):
    message = FlakyMessage(errors=_timeouts(1))
    assert asyncio.run(bot._reply(message, "hi")) is True
    assert len(message.attempts) == 2 and waits == [1]


def test_reply_gives_up_after_three_network_errors(waits, caplog):
    message = FlakyMessage(errors=[NetworkError("Bad Gateway") for _ in range(5)])
    with caplog.at_level(logging.WARNING, logger="bot"):
        assert asyncio.run(bot._reply(message, "hi")) is False
    assert len(message.attempts) == 3 and waits == [1, 3]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "3 attempt" in warnings[0].getMessage()


@pytest.mark.parametrize("error", [BadRequest("can't parse entities"), Forbidden("blocked"), RetryAfter(5)])
def test_reply_does_not_retry_permanent_errors(waits, error):
    message = FlakyMessage(errors=[error])
    assert asyncio.run(bot._reply(message, "hi")) is False
    assert len(message.attempts) == 1 and waits == []


def test_reply_lets_programming_errors_propagate(waits):
    message = FlakyMessage(errors=[KeyError("oops")])
    with pytest.raises(KeyError):
        asyncio.run(bot._reply(message, "hi"))


# ---------- form steps ----------


def test_start_moves_to_step_bug_even_if_prompt_fails(waits, service):
    state = asyncio.run(bot.feedback_start(_update(FlakyMessage(errors=_timeouts(3))), _context()))
    assert state == bot.STEP_BUG and service.events == ["started"]


@pytest.mark.parametrize("errors", [_timeouts(3), [Forbidden("blocked")]])
def test_bug_moves_to_step_2_when_prompt_fails(waits, errors):
    context = _context()
    state = asyncio.run(bot.feedback_bug(_update(FlakyMessage("the calc is wrong", errors)), context))
    assert state == bot.STEP_SUGGESTION
    assert context.user_data["bug"] == "the calc is wrong"


def test_resent_bug_is_stored_as_is(waits, service):
    context = _context(bug="same text")
    state = asyncio.run(bot.feedback_suggestion(_update(FlakyMessage("same text")), context))
    assert state == ConversationHandler.END
    assert service.stored == [("same text", "same text")]


@pytest.mark.parametrize("errors", [_timeouts(3), [Forbidden("blocked")]])
def test_suggestion_ends_even_if_thanks_fails(waits, service, errors):
    context = _context(bug="the calc is wrong")
    state = asyncio.run(bot.feedback_suggestion(_update(FlakyMessage("fix it", errors)), context))
    assert state == ConversationHandler.END
    assert context.user_data == {}
    assert service.stored == [("the calc is wrong", "fix it")] and service.events == ["submitted"]


def test_suggestion_does_not_end_when_storing_fails(waits, monkeypatch):
    monkeypatch.setattr(bot, "feedback_service", FakeService(store_error=RuntimeError("db down")))
    context = _context(bug="the calc is wrong")
    message = FlakyMessage("fix it")
    with pytest.raises(RuntimeError):
        asyncio.run(bot.feedback_suggestion(_update(message), context))
    assert context.user_data == {"bug": "the calc is wrong"}
    assert message.attempts == []


def test_cancel_ends_even_if_confirmation_fails(waits, service):
    context = _context(bug="half done")
    state = asyncio.run(bot.feedback_cancel(_update(FlakyMessage(errors=_timeouts(3))), context))
    assert state == ConversationHandler.END
    assert context.user_data == {} and service.events == ["cancelled"]


# ---------- answers captured outside the form ----------


def test_clarification_reply_stops_even_if_ack_fails(waits, monkeypatch):
    monkeypatch.setattr(bot.FeedbackService, "find_clarification_by_reply_prompt",
                        staticmethod(lambda user_id, message_id: {"id": "c1"}))

    async def fake_record(clarification, text, source):
        return "Thanks, got it."

    monkeypatch.setattr(bot, "record_answer", fake_record)
    message = FlakyMessage("my answer", _timeouts(3), reply_to=SimpleNamespace(message_id=7))
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.clarification_reply(_update(message), _context()))
    assert len(message.attempts) == 3


def test_runner_note_reply_stops_even_if_ack_fails(waits, monkeypatch):
    monkeypatch.setattr(bot, "get_admin_user_id", lambda: 42)
    monkeypatch.setattr(bot.FeedbackService, "find_auto_run_by_note_prompt",
                        staticmethod(lambda message_id: {"id": "r1"}))
    monkeypatch.setattr(bot.FeedbackService, "set_auto_run_decision",
                        staticmethod(lambda run_id, decision, note: True))
    message = FlakyMessage("use relative times", [Forbidden("blocked")], reply_to=SimpleNamespace(message_id=9))
    with pytest.raises(ApplicationHandlerStop):
        asyncio.run(bot.runner_note_reply(_update(message), _context()))


# ---------- application setup and error handler ----------


def test_build_application_timeouts_and_error_handler():
    app = bot.build_application("123:abc")
    assert app.bot.request.read_timeout == 10
    assert app.bot.request._client.timeout.connect == 10
    assert bot._on_error in app.error_handlers


def test_on_error_network_error_is_one_line(caplog):
    with caplog.at_level(logging.WARNING, logger="bot"):
        asyncio.run(bot._on_error(None, SimpleNamespace(error=TimedOut())))
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.WARNING and record.exc_info is None
    assert "TimedOut" in record.getMessage()


def test_on_error_programming_error_keeps_traceback(caplog):
    try:
        {}["missing"]
    except KeyError as exc:
        error = exc
    with caplog.at_level(logging.WARNING, logger="bot"):
        asyncio.run(bot._on_error(object(), SimpleNamespace(error=error)))
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.ERROR and record.exc_info is not None
