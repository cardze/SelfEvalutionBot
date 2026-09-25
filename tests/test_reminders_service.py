"""DB-backed tests for ReminderService, mirrors tests/test_actionable_queue.py's skip pattern.

Skipped when PostgreSQL is not reachable. Rows are created under a dedicated test
user id and removed afterwards.
"""

from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

import db
from reminders import MAX_ACTIVE_REMINDERS, ReminderLimitExceededError, ReminderService

TEST_USER_ID = -535353
OTHER_USER_ID = -535354


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
            cur.execute(
                "DELETE FROM reminders WHERE user_id IN (%s, %s)",
                (TEST_USER_ID, OTHER_USER_ID),
            )
        conn.commit()


@pytest.fixture
def clean():
    _cleanup()
    yield
    _cleanup()


def _now():
    return datetime.now(timezone.utc)


def test_create_and_list_round_trip(clean):
    next_fire_at = _now() + timedelta(minutes=10)
    row = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "Take the bread out", next_fire_at, False, None
    )
    assert row is not None
    assert row["message_text"] == "Take the bread out"

    active = ReminderService.list_active(TEST_USER_ID)
    assert [r["id"] for r in active] == [row["id"]]


def test_list_excludes_other_users_and_inactive(clean):
    next_fire_at = _now() + timedelta(minutes=10)
    mine = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "mine", next_fire_at, False, None
    )
    ReminderService.create_reminder(
        OTHER_USER_ID, OTHER_USER_ID, "not mine", next_fire_at, False, None
    )
    inactive = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "cancelled", next_fire_at, False, None
    )
    ReminderService.cancel(TEST_USER_ID, inactive["id"])

    active = ReminderService.list_active(TEST_USER_ID)
    assert [r["id"] for r in active] == [mine["id"]]


def test_cancel_only_affects_owner(clean):
    next_fire_at = _now() + timedelta(minutes=10)
    row = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "mine", next_fire_at, False, None
    )
    assert ReminderService.cancel(OTHER_USER_ID, row["id"]) is False
    assert ReminderService.list_active(TEST_USER_ID) != []
    assert ReminderService.cancel(TEST_USER_ID, row["id"]) is True
    assert ReminderService.list_active(TEST_USER_ID) == []


def test_cancel_unknown_or_foreign_id_returns_false_not_crash(clean):
    import uuid

    assert ReminderService.cancel(TEST_USER_ID, uuid.uuid4()) is False


def test_get_due_returns_only_active_due_rows(clean):
    now = _now()
    due = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "due", now - timedelta(seconds=5), False, None
    )
    future = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "future", now + timedelta(hours=1), False, None
    )
    inactive_due = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "inactive", now - timedelta(seconds=5), False, None
    )
    ReminderService.cancel(TEST_USER_ID, inactive_due["id"])

    due_rows = ReminderService.get_due(now)
    due_ids = set(r["id"] for r in due_rows if r["user_id"] == TEST_USER_ID)
    assert due["id"] in due_ids
    assert future["id"] not in due_ids
    assert inactive_due["id"] not in due_ids


def test_reschedule_advances_next_fire_at_and_stays_active(clean):
    now = _now()
    row = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "repeat", now, True, 300
    )
    new_next_fire_at = now + timedelta(seconds=300)
    assert ReminderService.reschedule(row["id"], new_next_fire_at) is True

    active = ReminderService.list_active(TEST_USER_ID)
    updated = next(r for r in active if r["id"] == row["id"])
    assert updated["next_fire_at"] == new_next_fire_at
    assert updated["active"] is True


def test_mark_delivered_deactivates_one_time_reminder(clean):
    now = _now()
    row = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "one-time", now, False, None
    )
    assert ReminderService.mark_delivered(row["id"]) is True
    assert ReminderService.list_active(TEST_USER_ID) == []


def test_create_reminder_enforces_active_cap(clean):
    now = _now()
    for i in range(MAX_ACTIVE_REMINDERS):
        row = ReminderService.create_reminder(
            TEST_USER_ID, TEST_USER_ID, "reminder " + str(i), now + timedelta(minutes=i + 1), False, None
        )
        assert row is not None

    assert len(ReminderService.list_active(TEST_USER_ID)) == MAX_ACTIVE_REMINDERS

    with pytest.raises(ReminderLimitExceededError):
        ReminderService.create_reminder(
            TEST_USER_ID, TEST_USER_ID, "one too many", now + timedelta(hours=1), False, None
        )

    # Cancelling one active reminder frees a slot for another creation.
    active = ReminderService.list_active(TEST_USER_ID)
    ReminderService.cancel(TEST_USER_ID, active[0]["id"])
    freed_row = ReminderService.create_reminder(
        TEST_USER_ID, TEST_USER_ID, "fits after cancel", now + timedelta(hours=1), False, None
    )
    assert freed_row is not None


def test_create_reminder_cap_is_per_user(clean):
    now = _now()
    for i in range(MAX_ACTIVE_REMINDERS):
        assert ReminderService.create_reminder(
            TEST_USER_ID, TEST_USER_ID, "reminder " + str(i), now + timedelta(minutes=i + 1), False, None
        ) is not None

    # OTHER_USER_ID has an independent cap; not affected by TEST_USER_ID being at the limit.
    other_row = ReminderService.create_reminder(
        OTHER_USER_ID, OTHER_USER_ID, "not capped", now + timedelta(minutes=1), False, None
    )
    assert other_row is not None
