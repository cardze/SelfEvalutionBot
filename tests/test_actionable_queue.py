"""DB-backed tests for FeedbackService clarification storage and the actionable queue.

Skipped when PostgreSQL is not reachable. Rows are created under a dedicated test
user id and removed afterwards.
"""

from contextlib import closing

import pytest

import db
from storage import ClarificationError, FeedbackService

TEST_USER_ID = -424242


def _db_available():
    try:
        db.init_database()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


def _cleanup():
    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feedback_events WHERE user_id = %s", (TEST_USER_ID,))
            cur.execute("DELETE FROM feedback_submissions WHERE user_id = %s", (TEST_USER_ID,))
        conn.commit()


@pytest.fixture
def clean():
    _cleanup()
    yield
    _cleanup()


def _ids(queue):
    return [row["id"] for row in queue["actionable"] if row["user_id"] == TEST_USER_ID]


def test_queue_lifecycle(clean):
    older = FeedbackService.store_submission(TEST_USER_ID, "older", "s")
    newer = FeedbackService.store_submission(TEST_USER_ID, "newer", "s")
    assert _ids(FeedbackService.get_actionable_feedback()) == [older, newer]

    # Draft on newer: waiting on admin, so parked out of the queue.
    c = FeedbackService.create_clarification(newer, "Q?", ["a", "b"])
    assert c["status"] == "pending_approval"
    assert _ids(FeedbackService.get_actionable_feedback()) == [older]

    # Sent: still excluded.
    assert FeedbackService.mark_sent(c["id"])
    assert not FeedbackService.mark_sent(c["id"])  # double approve is a no-op
    assert _ids(FeedbackService.get_actionable_feedback()) == [older]

    # Answered: reopened and ahead of the older item.
    assert FeedbackService.mark_answered(c["id"], "b", "option")
    assert not FeedbackService.mark_answered(c["id"], "a", "option")  # first answer wins
    queue = FeedbackService.get_actionable_feedback()
    assert _ids(queue) == [newer, older]
    ours = [row for row in queue["actionable"] if row["user_id"] == TEST_USER_ID]
    assert ours[0]["clarification_answer"] == "b"

    # Resolved: gone.
    FeedbackService.resolve_submission(newer)
    assert _ids(FeedbackService.get_actionable_feedback()) == [older]


def test_one_clarification_per_submission(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    FeedbackService.create_clarification(sub, "Q?", ["a", "b"])
    with pytest.raises(ClarificationError):
        FeedbackService.create_clarification(sub, "Q2?", ["c", "d"])


def test_cannot_draft_for_resolved(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    FeedbackService.resolve_submission(sub)
    with pytest.raises(ClarificationError):
        FeedbackService.create_clarification(sub, "Q?", ["a", "b"])


def test_discarded_stays_actionable(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    c = FeedbackService.create_clarification(sub, "Q?", ["a", "b"])
    assert FeedbackService.mark_discarded(c["id"])
    assert _ids(FeedbackService.get_actionable_feedback()) == [sub]


def test_reply_prompt_lookup(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    c = FeedbackService.create_clarification(sub, "Q?", ["a", "b"])
    FeedbackService.set_message_id(c["id"], "reply_prompt_message_id", 555)
    assert FeedbackService.find_clarification_by_reply_prompt(TEST_USER_ID, 555)["id"] == c["id"]
    assert FeedbackService.find_clarification_by_reply_prompt(12345, 555) is None


def test_db_rejects_unknown_event_type(clean):
    import psycopg

    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            with pytest.raises(psycopg.errors.CheckViolation):
                cur.execute(
                    "INSERT INTO feedback_events (user_id, event_type) VALUES (%s, 'bogus')",
                    (TEST_USER_ID,),
                )
        conn.rollback()


# ---------- wont_do, user filter, autonomous runs ----------


def _record(sub, event_type):
    assert FeedbackService.record_event(TEST_USER_ID, event_type, sub)


def test_wont_do_excluded(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    _record(sub, "wont_do")
    assert sub not in _ids(FeedbackService.get_actionable_feedback())


def test_user_filter(clean):
    sub = FeedbackService.store_submission(TEST_USER_ID, "bug", "s")
    mine = FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID)["actionable"]
    assert [r["id"] for r in mine] == [sub]
    other = FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID - 1)["actionable"]
    assert sub not in [r["id"] for r in other]


@pytest.fixture
def no_real_inflight_run():
    if FeedbackService.get_inflight_auto_run() is not None:
        pytest.skip("a real autonomous run is in flight")


def test_auto_run_lifecycle(clean, no_real_inflight_run):
    first = FeedbackService.store_submission(TEST_USER_ID, "first", "s")
    second = FeedbackService.store_submission(TEST_USER_ID, "second", "s")
    run = FeedbackService.create_auto_run(first, "auto/test", "/tmp/nowhere")
    try:
        # In-flight run hides its submission from the queue.
        assert _ids(FeedbackService.get_actionable_feedback()) == [second]
        assert FeedbackService.get_inflight_auto_run()["id"] == run["id"]

        # Single flight: a second run is rejected by the partial unique index.
        with pytest.raises(ClarificationError):
            FeedbackService.create_auto_run(second, "auto/test2", "/tmp/nowhere2")

        # Decisions only apply while awaiting a decision (or failed).
        assert not FeedbackService.set_auto_run_decision(run["id"], "merge")
        FeedbackService.update_auto_run(run["id"], stage="awaiting_decision", merge_request_message_id=77)
        assert FeedbackService.set_auto_run_decision(run["id"], "changes", "use relative times")
        row = FeedbackService.get_auto_run(run["id"])
        assert (row["decision"], row["decision_note"]) == ("changes", "use relative times")

        FeedbackService.update_auto_run(run["id"], note_prompt_message_id=88)
        assert FeedbackService.find_auto_run_by_note_prompt(88)["id"] == run["id"]

        with pytest.raises(ValueError):
            FeedbackService.update_auto_run(run["id"], branch="nope")
    finally:
        FeedbackService.update_auto_run(run["id"], stage="rejected")

    # Finished run: submission visible again unless an event excludes it.
    assert FeedbackService.get_inflight_auto_run() is None
    assert first in _ids(FeedbackService.get_actionable_feedback())
