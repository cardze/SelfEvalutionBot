"""Tests for the bot handlers that record admin decisions on autonomous runs (no database)."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest
from telegram.ext import ApplicationHandlerStop

import bot

ADMIN_ID = 111


class FakeQuery:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.answers = []
        self.markup_cleared = False

    async def answer(self, text=None, **kwargs):
        self.answers.append(text)

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        self.markup_cleared = reply_markup is None


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=700 + len(self.sent))


class FakeMessage:
    def __init__(self, text, reply_to_id=None):
        self.text = text
        self.reply_to_message = SimpleNamespace(message_id=reply_to_id) if reply_to_id else None
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


@pytest.fixture
def store(monkeypatch):
    calls = []
    state = {"run": None, "by_prompt": None, "applied": True}
    svc = bot.FeedbackService

    def rec(name, result=None):
        def fn(*args, **kwargs):
            calls.append((name, args, kwargs))
            return result() if callable(result) else result
        return fn

    monkeypatch.setenv("ADMIN_USER_ID", str(ADMIN_ID))
    monkeypatch.setattr(svc, "set_auto_run_decision", rec("decide", lambda: state["applied"]))
    monkeypatch.setattr(svc, "get_auto_run", rec("get", lambda: state["run"]))
    monkeypatch.setattr(svc, "update_auto_run", rec("update"))
    monkeypatch.setattr(svc, "find_auto_run_by_note_prompt", rec("find", lambda: state["by_prompt"]))
    return SimpleNamespace(calls=calls, state=state, names=lambda: [c[0] for c in calls])


def _run(handler, update, fake_bot=None):
    context = SimpleNamespace(bot=fake_bot or FakeBot())
    asyncio.run(handler(update, context))
    return context.bot


def _cb(query):
    return SimpleNamespace(callback_query=query)


def test_non_admin_decision_ignored(store):
    query = FakeQuery(f"run:{uuid4()}:m", user_id=999)
    _run(bot.runner_decision, _cb(query))
    assert store.names() == []


@pytest.mark.parametrize("action, decision", [("m", "merge"), ("r", "reject")])
def test_merge_and_reject_record_decision(store, action, decision):
    run_id = uuid4()
    query = FakeQuery(f"run:{run_id}:{action}", user_id=ADMIN_ID)
    _run(bot.runner_decision, _cb(query))
    assert store.calls[0][0] == "decide"
    assert store.calls[0][1] == (run_id, decision)
    assert query.answers[-1] == "Queued; the runner acts within an hour."
    assert query.markup_cleared


def test_decision_on_run_not_awaiting(store):
    store.state["applied"] = False
    query = FakeQuery(f"run:{uuid4()}:m", user_id=ADMIN_ID)
    _run(bot.runner_decision, _cb(query))
    assert query.answers[-1] == "This run is not awaiting a decision."
    assert not query.markup_cleared


def test_request_changes_sends_force_reply(store):
    run_id = uuid4()
    store.state["run"] = {"id": run_id, "stage": "awaiting_decision"}
    query = FakeQuery(f"run:{run_id}:c", user_id=ADMIN_ID)
    fake_bot = _run(bot.runner_decision, _cb(query))
    chat_id, text, kwargs = fake_bot.sent[0]
    assert chat_id == ADMIN_ID
    assert text == bot.RUN_NOTE_PROMPT_TEXT
    assert type(kwargs["reply_markup"]).__name__ == "ForceReply"
    assert ("update", (run_id,), {"note_prompt_message_id": 701}) in store.calls
    assert "decide" not in store.names()


def test_note_reply_records_changes_and_stops(store):
    run_id = uuid4()
    store.state["by_prompt"] = {"id": run_id}
    message = FakeMessage("use relative times only", reply_to_id=701)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=ADMIN_ID))
    with pytest.raises(ApplicationHandlerStop):
        _run(bot.runner_note_reply, update)
    assert ("decide", (run_id, "changes", "use relative times only"), {}) in store.calls
    assert "rebuild" in message.replies[-1]


def test_note_reply_from_non_admin_passes_through(store):
    store.state["by_prompt"] = {"id": uuid4()}
    message = FakeMessage("hi", reply_to_id=701)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=999))
    _run(bot.runner_note_reply, update)  # no ApplicationHandlerStop
    assert store.names() == []


def test_unmatched_reply_passes_through(store):
    store.state["by_prompt"] = None
    message = FakeMessage("some clarification answer", reply_to_id=123)
    update = SimpleNamespace(message=message, effective_user=SimpleNamespace(id=ADMIN_ID))
    _run(bot.runner_note_reply, update)  # falls through to the clarification handler
    assert message.replies == []


# ---------- ▶️ Build and 💡 suggestions (add-runner-signals) ----------


def test_build_tap_records_build(store):
    run_id = uuid4()
    query = FakeQuery(f"run:{run_id}:b", ADMIN_ID)
    _run(bot.runner_decision, SimpleNamespace(callback_query=query))
    assert store.calls[0] == ("decide", (run_id, "build"), {})
    assert query.answers == ["The build starts within an hour."] and query.markup_cleared


class SignalQuery(FakeQuery):
    def __init__(self, data, user_id):
        super().__init__(data, user_id)
        self.message = SimpleNamespace(text="💡 /meal sometimes fails for users")
        self.edited = None

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        self.edited = text


@pytest.fixture
def signal_store(monkeypatch):
    calls = []
    state = {"accepted": uuid4(), "dismissed": True}
    monkeypatch.setenv("ADMIN_USER_ID", str(ADMIN_ID))
    monkeypatch.setattr(bot.FeedbackService, "accept_signal",
                        lambda sid, admin: calls.append(("accept", sid, admin)) or state["accepted"])
    monkeypatch.setattr(bot.FeedbackService, "dismiss_signal",
                        lambda sid: calls.append(("dismiss", sid)) or state["dismissed"])
    return SimpleNamespace(calls=calls, state=state)


def test_plan_a_fix(signal_store):
    signal_id = uuid4()
    query = SignalQuery(f"sig:{signal_id}:p", ADMIN_ID)
    _run(bot.signal_decision, SimpleNamespace(callback_query=query))
    assert signal_store.calls == [("accept", signal_id, ADMIN_ID)]
    assert query.answers == [None]  # answered first, before any database work
    assert query.edited.startswith("💡 /meal sometimes fails for users\n\n📋 Queued as feedback")


def test_dismiss(signal_store):
    signal_id = uuid4()
    query = SignalQuery(f"sig:{signal_id}:d", ADMIN_ID)
    _run(bot.signal_decision, SimpleNamespace(callback_query=query))
    assert signal_store.calls == [("dismiss", signal_id)]
    assert query.edited.endswith("🙈 Dismissed for 7 days.")


def test_already_handled(signal_store):
    signal_store.state["accepted"] = None
    query = SignalQuery(f"sig:{uuid4()}:p", ADMIN_ID)
    _run(bot.signal_decision, SimpleNamespace(callback_query=query))
    assert query.edited.endswith("Already handled.")


@pytest.mark.parametrize("data", [f"sig:{uuid4()}:p", "sig:not-a-uuid:p", f"sig:{uuid4()}:x"])
def test_signal_taps_ignored(signal_store, data):
    user = 999 if data.endswith(":p") and "not-a-uuid" not in data else ADMIN_ID
    query = SignalQuery(data, user)
    _run(bot.signal_decision, SimpleNamespace(callback_query=query))
    assert signal_store.calls == [] and query.edited is None and query.answers == [None]
