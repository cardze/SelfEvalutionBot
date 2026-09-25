"""Tests for clarification draft validation and bot handlers (no database needed)."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from telegram.ext import ApplicationHandlerStop

import bot
import clarify
from clarify import DraftError, validate_draft

# ---------- validate_draft ----------


def test_valid_draft_is_stripped():
    question, options = validate_draft("  Did you mean?  ", [" A ", "B"])
    assert question == "Did you mean?"
    assert options == ["A", "B"]


@pytest.mark.parametrize(
    "question, options",
    [
        ("Q?", ["only one"]),
        ("Q?", ["a", "b", "c", "d", "e"]),
        ("Q?", ["a", "x" * 31]),
        ("Q?", ["same", "same"]),
        ("Q?", ["a", "  "]),
        ("", ["a", "b"]),
        ("q" * 501, ["a", "b"]),
    ],
)
def test_invalid_drafts_rejected(question, options):
    with pytest.raises(DraftError):
        validate_draft(question, options)


def test_limits_are_inclusive():
    validate_draft("q" * 500, ["x" * 30, "b", "c", "d"])


# ---------- fakes ----------

ADMIN_ID = 111
SUBMITTER_ID = 222


class FakeQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(text)


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=900 + len(self.sent))


class FakeMessage:
    def __init__(self, text, reply_to_id=None):
        self.text = text
        self.reply_to_message = SimpleNamespace(message_id=reply_to_id) if reply_to_id else None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


def _clarification(status="sent", **overrides):
    row = {
        "id": uuid4(),
        "feedback_submission_id": uuid4(),
        "user_id": SUBMITTER_ID,
        "bug_text": "I want a notice function",
        "suggestion_text": "Notify me",
        "question": "Did you mean?",
        "options": ["Reminder", "Recurring"],
        "status": status,
    }
    row.update(overrides)
    return row


@pytest.fixture
def store(monkeypatch):
    """Patch FeedbackService with an in-memory recorder."""
    calls = []
    state = {"clarification": None, "by_prompt": None, "resolved": False}
    svc = bot.FeedbackService

    def rec(name, result=None):
        def fn(*args):
            calls.append((name, args))
            return result() if callable(result) else result
        return fn

    monkeypatch.setenv("ADMIN_USER_ID", str(ADMIN_ID))
    monkeypatch.setattr(svc, "get_clarification", rec("get", lambda: state["clarification"]))
    monkeypatch.setattr(
        svc, "find_clarification_by_reply_prompt", rec("find", lambda: state["by_prompt"])
    )
    monkeypatch.setattr(svc, "mark_sent", rec("mark_sent", True))
    monkeypatch.setattr(svc, "revert_to_pending", rec("revert", True))
    monkeypatch.setattr(svc, "mark_discarded", rec("discard", True))
    monkeypatch.setattr(svc, "mark_answered", rec("answered", True))
    monkeypatch.setattr(svc, "set_message_id", rec("set_msg"))
    monkeypatch.setattr(svc, "record_event", rec("event", True))
    monkeypatch.setattr(svc, "is_resolved", rec("is_resolved", lambda: state["resolved"]))
    return SimpleNamespace(calls=calls, state=state, names=lambda: [c[0] for c in calls])


def _callback_update(query):
    return SimpleNamespace(callback_query=query)


def _run(handler, update, fake_bot=None):
    context = SimpleNamespace(bot=fake_bot or FakeBot())
    asyncio.run(handler(update, context))
    return context.bot


# ---------- approval ----------


def test_non_admin_approval_is_ignored(store):
    c = _clarification(status="pending_approval")
    store.state["clarification"] = c
    query = FakeQuery(f"apv:{c['id']}:y", user_id=SUBMITTER_ID)
    fake_bot = _run(bot.clarification_approval, _callback_update(query))
    assert fake_bot.sent == []
    assert "mark_sent" not in store.names()


def test_admin_approve_delivers_question_as_plain_text(store):
    c = _clarification(status="pending_approval", question="Hi. (Really!)")
    store.state["clarification"] = c
    query = FakeQuery(f"apv:{c['id']}:y", user_id=ADMIN_ID)
    fake_bot = _run(bot.clarification_approval, _callback_update(query))

    chat_id, text, kwargs = fake_bot.sent[0]
    assert chat_id == SUBMITTER_ID
    assert text == "Hi. (Really!)"
    assert "parse_mode" not in kwargs
    buttons = [row[0].text for row in kwargs["reply_markup"].inline_keyboard]
    assert buttons == ["Reminder", "Recurring", clarify.SOMETHING_ELSE_LABEL]
    assert ("event", (SUBMITTER_ID, "clarification_requested", c["feedback_submission_id"])) in store.calls
    assert query.edits[-1].endswith("✅ Sent")


def test_admin_approve_send_failure_reverts(store):
    c = _clarification(status="pending_approval")
    store.state["clarification"] = c

    class FailingBot(FakeBot):
        async def send_message(self, chat_id, text, **kwargs):
            raise RuntimeError("Forbidden: bot was blocked by the user")

    query = FakeQuery(f"apv:{c['id']}:y", user_id=ADMIN_ID)
    _run(bot.clarification_approval, _callback_update(query), FailingBot())
    assert "revert" in store.names()
    assert "event" not in store.names()
    assert "Send failed" in query.edits[-1]


def test_admin_discard(store):
    c = _clarification(status="pending_approval")
    store.state["clarification"] = c
    query = FakeQuery(f"apv:{c['id']}:n", user_id=ADMIN_ID)
    fake_bot = _run(bot.clarification_approval, _callback_update(query))
    assert "discard" in store.names()
    assert fake_bot.sent == []
    assert query.edits[-1].endswith("❌ Discarded")


def test_approve_twice_sends_nothing(store):
    store.state["clarification"] = _clarification(status="sent")
    c = store.state["clarification"]
    query = FakeQuery(f"apv:{c['id']}:y", user_id=ADMIN_ID)
    fake_bot = _run(bot.clarification_approval, _callback_update(query))
    assert fake_bot.sent == []
    assert "mark_sent" not in store.names()


# ---------- answers ----------


def test_wrong_user_answer_is_ignored(store):
    c = _clarification()
    store.state["clarification"] = c
    query = FakeQuery(f"clr:{c['id']}:0", user_id=999)
    _run(bot.clarification_answer, _callback_update(query))
    assert "answered" not in store.names()


def test_option_tap_stores_answer(store):
    c = _clarification()
    store.state["clarification"] = c
    query = FakeQuery(f"clr:{c['id']}:1", user_id=SUBMITTER_ID)
    _run(bot.clarification_answer, _callback_update(query))
    assert ("answered", (c["id"], "Recurring", "option")) in store.calls
    assert ("event", (SUBMITTER_ID, "clarified", c["feedback_submission_id"])) in store.calls
    assert query.edits[-1].endswith("Thanks! Noted: Recurring")


def test_option_tap_on_resolved_submission(store):
    c = _clarification()
    store.state["clarification"] = c
    store.state["resolved"] = True
    query = FakeQuery(f"clr:{c['id']}:0", user_id=SUBMITTER_ID)
    _run(bot.clarification_answer, _callback_update(query))
    assert query.edits[-1].endswith("Thanks! This was already addressed.")


def test_option_tap_after_answered(store):
    c = _clarification(status="answered")
    store.state["clarification"] = c
    query = FakeQuery(f"clr:{c['id']}:0", user_id=SUBMITTER_ID)
    _run(bot.clarification_answer, _callback_update(query))
    assert "answered" not in store.names()
    assert query.answers[-1] == "Already answered, thanks!"


def test_something_else_sends_force_reply(store):
    c = _clarification()
    store.state["clarification"] = c
    query = FakeQuery(f"clr:{c['id']}:x", user_id=SUBMITTER_ID)
    fake_bot = _run(bot.clarification_answer, _callback_update(query))
    chat_id, text, kwargs = fake_bot.sent[0]
    assert chat_id == SUBMITTER_ID
    assert text == clarify.REPLY_PROMPT_TEXT
    assert type(kwargs["reply_markup"]).__name__ == "ForceReply"
    assert ("set_msg", (c["id"], "reply_prompt_message_id", 901)) in store.calls
    assert "answered" not in store.names()


def test_matched_reply_is_captured_and_stops_propagation(store):
    c = _clarification()
    store.state["by_prompt"] = c
    message = FakeMessage("I meant a countdown timer", reply_to_id=901)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=SUBMITTER_ID))
    with pytest.raises(ApplicationHandlerStop):
        _run(bot.clarification_reply, update)
    assert ("answered", (c["id"], "I meant a countdown timer", "free_text")) in store.calls
    assert message.replies[-1] == "Thanks! Noted: I meant a countdown timer"


def test_unmatched_reply_passes_through(store):
    store.state["by_prompt"] = None
    message = FakeMessage("some feedback text", reply_to_id=123)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=SUBMITTER_ID))
    _run(bot.clarification_reply, update)  # must not raise ApplicationHandlerStop
    assert message.replies == []
    assert "answered" not in store.names()
