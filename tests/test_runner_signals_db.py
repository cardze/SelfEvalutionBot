"""Runner signals storage: cursor, lifecycle and held-plan decisions (DB-backed).

Touches only `test:` signals and TEST_USER_ID rows, and restores the real cursor row afterwards.
"""

from contextlib import closing
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

import db
from storage import FeedbackService

TEST_USER_ID = -646464
NOW = datetime.now(timezone.utc)


def _db_available():
    try:
        db.init_database()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


def _sql(query, params=(), fetch=False):
    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall() if fetch else None
        conn.commit()
    return rows


def _cleanup():
    _sql("DELETE FROM runner_signals WHERE fingerprint LIKE 'test:%%'")
    _sql("DELETE FROM feedback_events WHERE user_id = %s", (TEST_USER_ID,))
    _sql("DELETE FROM feedback_submissions WHERE user_id = %s", (TEST_USER_ID,))


@pytest.fixture(autouse=True)
def clean():
    saved = FeedbackService.get_signal_cursor()
    _cleanup()
    yield
    _cleanup()
    _sql("DELETE FROM runner_signal_cursor")
    if saved:
        _sql("INSERT INTO runner_signal_cursor (id, inode, byte_offset) VALUES (true, %s, %s)",
             (saved["inode"], saved["byte_offset"]))


def _event(name="a", kind="unhandled", ts=None, user=7):
    return {"fingerprint": f"test:{name}", "kind": kind, "exc": "KeyError", "file": "bot.py",
            "func": "meal_picker", "line": 3, "known_cause": None, "user": user, "ts": ts or NOW}


def _signal(name="a"):
    return _sql("SELECT id, status, occurrences, users, recent FROM runner_signals WHERE fingerprint = %s",
                (f"test:{name}",), fetch=True)[0]


def _record(*events):
    FeedbackService.record_signal_events(list(events), 1, 100, NOW)


def _suggest(name="a"):
    signal_id = _signal(name)[0]
    FeedbackService.mark_signal_suggested(signal_id, "💡 summary", 55)
    return signal_id


# ---------- cursor ----------


def test_events_and_cursor_commit_together():
    bad = _event("b", kind="bogus")  # violates the kind CHECK: the whole batch must roll back
    with pytest.raises(psycopg.Error):
        FeedbackService.record_signal_events([_event("a"), bad], 9, 999, NOW)
    assert _sql("SELECT 1 FROM runner_signals WHERE fingerprint = 'test:a'", fetch=True) == []
    FeedbackService.record_signal_events([_event("a")], 9, 999, NOW)  # the retry counts it once
    assert _signal()[2] == 1
    assert FeedbackService.get_signal_cursor() == {"inode": 9, "byte_offset": 999}


# ---------- recording ----------


def test_counts_users_and_window():
    old = NOW - timedelta(hours=30)
    _record(_event(ts=old, user=1), _event(user=1), _event(user=2), _event(user=None))
    _, status, occurrences, users, recent = _signal()
    assert status == "observed" and occurrences == 4 and sorted(users) == [1, 2] and len(recent) == 3


# ---------- lifecycle ----------


def test_candidates_include_observed_only_once_suggested():
    _record(_event())
    assert "test:a" in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, timedelta(days=7))]
    _suggest()
    assert "test:a" not in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, timedelta(days=7))]
    assert FeedbackService.count_signals_suggested_since(NOW - timedelta(hours=1)) >= 1


def test_accept_is_one_submission_even_on_double_tap():
    _record(_event())
    signal_id = _suggest()
    first = FeedbackService.accept_signal(signal_id, TEST_USER_ID)
    second = FeedbackService.accept_signal(signal_id, TEST_USER_ID)
    assert first is not None and second is None
    rows = _sql("SELECT bug_text, suggestion_text FROM feedback_submissions WHERE user_id = %s",
                (TEST_USER_ID,), fetch=True)
    assert rows == [("💡 summary", "Find the cause and fix it so this no longer happens. "
                                   "(Suggested by the runner, signal test:a.)")]
    assert FeedbackService.is_signal_submission(first)
    events = _sql("SELECT event_type FROM feedback_events WHERE feedback_submission_id = %s",
                  (first,), fetch=True)
    assert events == [("submitted",)]


def test_accept_requires_suggested():
    _record(_event())
    assert FeedbackService.accept_signal(_signal()[0], TEST_USER_ID) is None  # still 'observed'


def test_resolved_fix_resets_and_regression_is_counted_again():
    _record(_event(), _event())
    submission = FeedbackService.accept_signal(_suggest(), TEST_USER_ID)
    FeedbackService.resolve_submission(submission)
    FeedbackService.settle_accepted_signals()
    _, status, occurrences, users, recent = _signal()
    assert (status, occurrences, users, recent) == ("observed", 0, [], [])
    assert "test:a" not in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, timedelta(days=7))]
    _record(_event())
    assert "test:a" in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, timedelta(days=7))]


def test_dropped_work_dismisses_the_signal():
    _record(_event())
    submission = FeedbackService.accept_signal(_suggest(), TEST_USER_ID)
    FeedbackService.record_event(TEST_USER_ID, "wont_do", submission)
    FeedbackService.settle_accepted_signals()
    assert _signal()[1] == "dismissed"


def test_dismiss_snooze_needs_time_and_new_occurrences():
    _record(_event(ts=NOW - timedelta(days=10)))
    signal_id = _suggest()
    assert FeedbackService.dismiss_signal(signal_id) and not FeedbackService.dismiss_signal(signal_id)
    week = timedelta(days=7)
    _sql("UPDATE runner_signals SET status_changed_at = %s WHERE id = %s", (NOW - timedelta(days=8), signal_id))
    assert "test:a" not in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, week)]
    _record(_event(ts=NOW - timedelta(days=9)))  # before the dismissal: still snoozed
    assert "test:a" not in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, week)]
    _record(_event())                            # after the dismissal and the snooze
    assert "test:a" in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, week)]
    _sql("UPDATE runner_signals SET status_changed_at = %s WHERE id = %s", (NOW - timedelta(days=2), signal_id))
    assert "test:a" not in [s["fingerprint"] for s in FeedbackService.signal_candidates(NOW, week)]


# ---------- held-plan decisions ----------


@pytest.fixture
def planned_run():
    if FeedbackService.get_inflight_auto_run() is not None:
        pytest.skip("a real autonomous run is in flight")
    submission = FeedbackService.store_submission(TEST_USER_ID, "bug", "fix")
    run = FeedbackService.create_auto_run(submission, "auto/test", "/tmp/none")
    FeedbackService.update_auto_run(run["id"], stage="planned")
    return run["id"], submission


def _gate(submission):
    _record(_event("gate"))
    _sql("UPDATE runner_signals SET status = 'accepted', feedback_submission_id = %s "
         "WHERE fingerprint = 'test:gate'", (submission,))


def test_ungated_planned_run_accepts_no_decision(planned_run):
    run_id, _ = planned_run
    for decision in ("build", "reject", "merge", "changes"):
        assert not FeedbackService.set_auto_run_decision(run_id, decision)


def test_gated_planned_run_accepts_build_and_reject_only(planned_run):
    run_id, submission = planned_run
    _gate(submission)
    assert not FeedbackService.set_auto_run_decision(run_id, "merge")
    assert not FeedbackService.set_auto_run_decision(run_id, "changes")
    assert FeedbackService.set_auto_run_decision(run_id, "build")
    assert FeedbackService.set_auto_run_decision(run_id, "reject")


def test_build_is_never_accepted_at_merge_time(planned_run):
    run_id, submission = planned_run
    _gate(submission)
    FeedbackService.update_auto_run(run_id, stage="awaiting_decision")
    assert not FeedbackService.set_auto_run_decision(run_id, "build")
    assert FeedbackService.set_auto_run_decision(run_id, "merge")
