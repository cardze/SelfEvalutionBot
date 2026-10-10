"""Runner signals: validation, reading, impact rendering and the suggestion loop (no database)."""

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from runner import signals, templates
from runner.config import Config

REPO = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 4, 4, 0, tzinfo=timezone.utc)
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


@pytest.fixture
def code(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    (main / "tests").mkdir(parents=True)
    (main / "bot.py").write_text("async def meal_picker(update, context):\n    pass\n\ndef helper():\n    pass\n")
    (main / "tests/test_x.py").write_text("def test_x():\n    pass\n")
    _git(main, "init", "-q", "-b", "main")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    (main / "untracked.py").write_text("def meal_picker():\n    pass\n")
    config = Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
                    runner_home=tmp_path / "rh")
    return signals.MainCode(config)


def _event(**overrides):
    event = {"v": 1, "ts": (NOW - timedelta(minutes=1)).isoformat(), "kind": "unhandled",
             "exc": "telegram.error.BadRequest", "file": "bot.py", "func": "meal_picker", "line": 3,
             "user": 7, "known_cause": "reply_target_gone"}
    event.update(overrides)
    return json.dumps({k: v for k, v in event.items() if v is not None}).encode()


# ---------- validation ----------


def test_valid_event(code):
    event = signals.validate(_event(), code, NOW)
    assert event["fingerprint"] == "unhandled:telegram.error.BadRequest:bot.py:meal_picker"
    assert event["user"] == 7 and event["ts"].tzinfo is not None


@pytest.mark.parametrize("overrides", [
    {"func": "ignore_all_rules"},                  # not defined in the file on main
    {"file": "untracked.py"},                      # not tracked on main
    {"file": "tests/test_x.py", "func": "test_x"},  # test code
    {"file": ".venv/lib/site-packages/x.py"},
    {"file": "../etc/passwd"},
    {"func": "meal picker"},
    {"exc": "Bad Request: x"},
    {"ts": "2026-10-04T03:59:00"},                 # no timezone
    {"ts": (NOW + timedelta(hours=1)).isoformat()},  # in the future
    {"user": "908274693"},
    {"user": True},
    {"line": 0},
    {"known_cause": "made_up"},
    {"kind": "other"},
    {"v": 2},
    {"func": None},                                # file without func
])
def test_invalid_events_are_dropped(code, overrides):
    assert signals.validate(_event(**overrides), code, NOW) is None


def test_garbage_is_dropped(code):
    assert signals.validate(b"not json", code, NOW) is None
    assert signals.validate(b"[1, 2]", code, NOW) is None
    assert signals.validate(b"\xff\xfe", code, NOW) is None


def test_fingerprints_per_kind(code):
    reply = signals.validate(_event(kind="reply_failed", exc="telegram.error.TimedOut"), code, NOW)
    assert reply["fingerprint"] == "reply_failed:telegram.error.TimedOut:meal_picker"
    reminder = signals.validate(_event(kind="reminder_failed", file=None, func=None, line=None), code, NOW)
    assert reminder["fingerprint"] == "reminder_failed:telegram.error.BadRequest"


# ---------- reading ----------


def test_first_read_starts_at_end(tmp_path):
    path = tmp_path / "signals.jsonl"
    path.write_text('{"a": 1}\n')
    lines, inode, offset, skipped = signals.read_new_lines(path, None)
    assert lines == [] and offset == path.stat().st_size and skipped == 0


def test_no_file():
    assert signals.read_new_lines(Path("/nonexistent/signals.jsonl"), None) is None


def test_reads_complete_lines_only(tmp_path):
    path = tmp_path / "signals.jsonl"
    path.write_text('{"a": 1}\n{"b": 2}\n{"c": ')
    cursor = {"inode": path.stat().st_ino, "byte_offset": 0}
    lines, _, offset, _ = signals.read_new_lines(path, cursor)
    assert lines == [b'{"a": 1}', b'{"b": 2}'] and offset == len('{"a": 1}\n{"b": 2}\n')
    with open(path, "a") as f:
        f.write('3}\n')
    lines, _, _, _ = signals.read_new_lines(path, {"inode": path.stat().st_ino, "byte_offset": offset})
    assert lines == [b'{"c": 3}']


def test_rotation_and_truncation_restart_from_zero(tmp_path):
    path = tmp_path / "signals.jsonl"
    path.write_text('{"new": 1}\n')
    st = path.stat()
    rotated = {"inode": st.st_ino + 1, "byte_offset": 5}
    assert signals.read_new_lines(path, rotated)[0] == [b'{"new": 1}']
    truncated = {"inode": st.st_ino, "byte_offset": 10_000}
    assert signals.read_new_lines(path, truncated)[0] == [b'{"new": 1}']


def test_read_cap_cuts_at_a_line_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "MAX_READ", 20)
    path = tmp_path / "signals.jsonl"
    path.write_text('{"a": 11111}\n{"b": 22222}\n')
    cursor = {"inode": path.stat().st_ino, "byte_offset": 0}
    lines, _, offset, _ = signals.read_new_lines(path, cursor)
    assert lines == [b'{"a": 11111}'] and offset == 13
    lines, _, _, _ = signals.read_new_lines(path, {"inode": cursor["inode"], "byte_offset": offset})
    assert lines == [b'{"b": 22222}']


def test_overlong_line_is_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(signals, "MAX_READ", 8)
    path = tmp_path / "signals.jsonl"
    path.write_text("x" * 50 + "\n")
    lines, _, offset, skipped = signals.read_new_lines(path, {"inode": path.stat().st_ino, "byte_offset": 0})
    assert lines == [] and offset == 8 and skipped == 1


# ---------- impact ----------


@pytest.fixture(scope="module")
def features():
    return signals.handler_map((REPO / "bot.py").read_text())


def _signal(**overrides):
    signal = {"fingerprint": "unhandled:test", "kind": "unhandled", "exc": "telegram.error.BadRequest", "file": "bot.py",
              "func": "meal_picker", "last_line": 249, "known_cause": "reply_target_gone",
              "occurrences": 2, "users": [7], "recent": [],
              "last_seen": datetime(2026, 9, 28, 22, 29, tzinfo=timezone.utc)}
    signal.update(overrides)
    return signal


def test_handler_map_of_current_bot(features):
    assert features["meal_picker"] == ("command", "/meal")
    assert features["feedback_bug"] == ("command", "/feedback")
    assert features["feedback_suggestion"] == ("command", "/feedback")
    assert features["runner_decision"] == ("button", "the buttons on runner messages")
    assert features["signal_decision"] == ("button", "the 💡 suggestion buttons")


def test_render_command_error(features):
    text = signals.render(_signal(), features, NOW)
    assert text.splitlines() == [
        "💡 /meal sometimes fails for users",
        "Impact: the user sends /meal and probably gets no reply",
        "Who:    1 user · 2 times · last 2026-09-29 06:29 · none in the last 24 h",
        "Cause:  the user's message was gone before the bot replied",
        "Where:  BadRequest in bot.py → meal_picker (line 249)",
    ]


def test_render_without_cause_or_users(features):
    text = signals.render(_signal(known_cause=None, users=[], func="helper_thing", occurrences=1,
                                  recent=[(NOW - timedelta(hours=1)).isoformat()]), features, NOW)
    assert "Cause:" not in text and "users unknown" in text and "1 in the last 24 h" in text
    assert text.startswith("💡 The bot hit an unhandled error in internal code (helper_thing)")


def test_render_button_and_reminders(features):
    assert signals.render(_signal(func="runner_decision"), features, NOW).startswith(
        "💡 The buttons on runner messages sometimes fail")
    reminder = signals.render(_signal(kind="reminder_failed", file=None, func=None, known_cause=None),
                              features, NOW)
    assert reminder.startswith("💡 Reminders are failing to send") and "Where:  BadRequest" in reminder


def test_render_reply_failed(features):
    text = signals.render(_signal(kind="reply_failed", func="feedback_bug", known_cause="timed_out",
                                  exc="telegram.error.TimedOut"), features, NOW)
    assert text.startswith("💡 Replies in /feedback are not getting through")
    assert "Cause:  Telegram did not answer in time" in text


def test_thresholds():
    assert signals.threshold_met(_signal(occurrences=1), NOW)
    recent = [(NOW - timedelta(hours=h)).isoformat() for h in (1, 2)]
    assert not signals.threshold_met(_signal(kind="reply_failed", recent=recent), NOW)
    old = recent + [(NOW - timedelta(hours=30)).isoformat()]
    assert not signals.threshold_met(_signal(kind="reply_failed", recent=old), NOW)
    assert signals.threshold_met(_signal(kind="reply_failed", recent=recent + [NOW.isoformat()]), NOW)


# ---------- suggestion loop ----------


class FakeStore:
    def __init__(self, candidates, suggested_today=0):
        self.candidates = candidates
        self.suggested_today = suggested_today
        self.marked = []
        self.recorded = None

    def get_signal_cursor(self):
        return None

    def record_signal_events(self, events, inode, offset, now):
        self.recorded = (events, inode, offset)

    def settle_accepted_signals(self):
        return 0, 0

    def count_signals_suggested_since(self, since):
        return self.suggested_today

    def signal_candidates(self, now, snooze):
        return self.candidates

    def mark_signal_suggested(self, signal_id, summary, message_id):
        self.marked.append((signal_id, message_id))


@pytest.fixture
def loop(code, monkeypatch):
    def setup(candidates, suggested_today=0, send=None):
        store = FakeStore(candidates, suggested_today)
        for name in ("get_signal_cursor", "record_signal_events", "settle_accepted_signals",
                     "count_signals_suggested_since", "signal_candidates", "mark_signal_suggested"):
            monkeypatch.setattr(signals.FeedbackService, name, getattr(store, name))
        sent = []
        monkeypatch.setattr(signals.notify, "signal", send or (lambda sid, text: sent.append(sid) or 100))
        return store, sent
    return setup


def test_daily_cap(loop, code):
    store, sent = loop([_signal(id=i) for i in range(5)])
    stats = signals.scan(code.config, NOW)
    assert sent == [0, 1, 2] and stats["suggested"] == 3


def test_cap_counts_earlier_suggestions(loop, code):
    store, sent = loop([_signal(id=i) for i in range(5)], suggested_today=2)
    signals.scan(code.config, NOW)
    assert sent == [0]


def test_below_threshold_is_not_sent(loop, code):
    store, sent = loop([_signal(id=1, kind="reply_failed", recent=[NOW.isoformat()])])
    signals.scan(code.config, NOW)
    assert sent == []


def test_failed_send_is_retried_later(loop, code):
    def boom(sid, text):
        raise RuntimeError("telegram down")
    store, _ = loop([_signal(id=1)], send=boom)
    stats = signals.scan(code.config, NOW)
    assert store.marked == [] and stats["suggested"] == 0


def test_scan_records_validated_events_with_cursor(loop, code, monkeypatch):
    events_file = code.config.signals_file
    events_file.parent.mkdir(parents=True)
    events_file.write_bytes(_event() + b"\n" + _event(func="ignore_all_rules") + b"\n")
    store, _ = loop([])
    monkeypatch.setattr(signals.FeedbackService, "get_signal_cursor",
                        lambda: {"inode": events_file.stat().st_ino, "byte_offset": 0})
    stats = signals.scan(code.config, NOW)
    events, inode, offset = store.recorded
    assert [e["func"] for e in events] == ["meal_picker"] and stats == {
        "read": 1, "dropped": 1, "suggested": 0, "reset": 0, "dismissed": 0}
    assert offset == events_file.stat().st_size


# ---------- launchd ----------


def test_only_the_bot_plist_sets_the_events_file(tmp_path):
    config = Config(main=tmp_path, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"))
    paths = {p.name: p.read_text() for p in templates.render_plists(config, tmp_path / "out")}
    assert "SEB_SIGNALS_FILE" in paths["com.seb.bot.plist"]
    assert "/.seb-runner/logs/signals.jsonl" in paths["com.seb.bot.plist"]
    assert "SEB_SIGNALS_FILE" not in paths["com.seb.runner.plist"]
