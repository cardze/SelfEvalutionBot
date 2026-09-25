"""Reminder/notice parsing, storage, and delivery.

Follows the repo's existing conventions:
- Parsing uses only `re`/`datetime` (no `eval`/`exec`), mirroring the calculator's
  AST-allowlist security precedent in `bot.py`.
- `ReminderService` is an all-`@staticmethod` class over `db.get_connection()` /
  `closing(conn)` / `with conn.cursor()`, mirroring `storage.FeedbackService`.
- All reminder times are computed and stored in UTC (`datetime.now(timezone.utc)`),
  never host-local/server-default time (see design.md Non-Goals).
"""

import asyncio
import logging
import re
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from psycopg.rows import dict_row

from db import get_connection

logger = logging.getLogger(__name__)

# Minimum allowed interval for repeating notices, in seconds.
# Must match the reminders_interval_seconds_check CHECK constraint in sql/init.sql
# (enforced by tests/test_reminders_schema.py).
MIN_INTERVAL_SECONDS = 60

_UNIT_SECONDS = dict(m=60, h=3600, d=86400)

_RELATIVE_RE = re.compile(r"^in\s+(\d+)([mhd])$", re.IGNORECASE)
_ABSOLUTE_RE = re.compile(r"^at\s+([01]?\d|2[0-3]):([0-5]\d)$", re.IGNORECASE)
_INTERVAL_RE = re.compile(r"^every\s+(\d+)([mhd])$", re.IGNORECASE)

USAGE = (
    "Usage: /remind <when> <message>\n"
    "  /remind in 10m Take the bread out\n"
    "  /remind in 2h Check the oven\n"
    "  /remind at 14:30 Call the dentist\n"
    "  /remind every 1h Drink water\n"
    "Accepted units: m (minutes), h (hours), d (days).\n"
    "Times are interpreted in UTC. Minimum repeat interval is "
    + str(MIN_INTERVAL_SECONDS) + " seconds."
)


class ReminderParseError(ValueError):
    """Raised when a `<when>` expression cannot be parsed. Message is usage-style."""


def parse_relative(when: str, now: Optional[datetime] = None) -> datetime:
    """Parse `in <n>m/h/d` into an absolute UTC datetime.

    Raises:
        ReminderParseError: if `when` doesn't match the expected grammar.
    """
    match = _RELATIVE_RE.match(when.strip())
    if not match:
        raise ReminderParseError("Could not understand the time expression: " + repr(when) + ". " + USAGE)
    amount, unit = int(match.group(1)), match.group(2).lower()
    if amount <= 0:
        raise ReminderParseError("Relative offset must be a positive number: " + repr(when) + ". " + USAGE)
    now = now or datetime.now(timezone.utc)
    return now + timedelta(seconds=amount * _UNIT_SECONDS[unit])


def parse_absolute(when: str, now: Optional[datetime] = None) -> datetime:
    """Parse `at HH:MM` into an absolute UTC datetime (today, or tomorrow if already passed).

    Raises:
        ReminderParseError: if `when` doesn't match the expected grammar.
    """
    match = _ABSOLUTE_RE.match(when.strip())
    if not match:
        raise ReminderParseError("Could not understand the time expression: " + repr(when) + ". " + USAGE)
    hour, minute = int(match.group(1)), int(match.group(2))
    now = now or datetime.now(timezone.utc)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def parse_interval(when: str) -> int:
    """Parse `every <n>m/h/d` into a whole-second interval.

    Raises:
        ReminderParseError: if `when` doesn't match the grammar or the interval
            is below `MIN_INTERVAL_SECONDS`.
    """
    match = _INTERVAL_RE.match(when.strip())
    if not match:
        raise ReminderParseError("Could not understand the time expression: " + repr(when) + ". " + USAGE)
    amount, unit = int(match.group(1)), match.group(2).lower()
    interval_seconds = amount * _UNIT_SECONDS[unit]
    if interval_seconds < MIN_INTERVAL_SECONDS:
        raise ReminderParseError(
            "Minimum repeat interval is " + str(MIN_INTERVAL_SECONDS)
            + " seconds; got " + str(interval_seconds) + "s. " + USAGE
        )
    return interval_seconds


def parse_when(when: str, now: Optional[datetime] = None) -> tuple[datetime, bool, Optional[int]]:
    """Parse a full `<when>` token (`in ...`, `at ...`, or `every ...`).

    Returns:
        (next_fire_at, is_recurring, interval_seconds)

    Raises:
        ReminderParseError: on anything that doesn't match one of the three forms.
    """
    when = (when or "").strip()
    now = now or datetime.now(timezone.utc)
    lowered = when.lower()
    if lowered.startswith("every"):
        interval_seconds = parse_interval(when)
        return now + timedelta(seconds=interval_seconds), True, interval_seconds
    if lowered.startswith("in"):
        return parse_relative(when, now), False, None
    if lowered.startswith("at"):
        return parse_absolute(when, now), False, None
    raise ReminderParseError("Could not understand the time expression: " + repr(when) + ". " + USAGE)


class ReminderService:
    """Service for storing and retrieving reminders/notices, following FeedbackService's pattern."""

    @staticmethod
    def create_reminder(
        user_id: int,
        chat_id: int,
        message_text: str,
        next_fire_at: datetime,
        is_recurring: bool,
        interval_seconds: Optional[int] = None,
    ) -> Optional[dict]:
        """Insert a new reminder row. Returns the created row, or None on failure."""
        try:
            conn = get_connection()
            with closing(conn):
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(
                        """
                        INSERT INTO reminders
                            (user_id, chat_id, message_text, is_recurring, interval_seconds, next_fire_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (user_id, chat_id, message_text, is_recurring, interval_seconds, next_fire_at),
                    )
                    row = cur.fetchone()
                conn.commit()
            reminder_id = row["id"] if row else None
            logger.info("Reminder created: user_id=%s, reminder_id=%s", user_id, reminder_id)
            return row
        except Exception as e:
            logger.error("Failed to create reminder: user_id=%s, error=%s", user_id, str(e))
            return None

    @staticmethod
    def list_active(user_id: int) -> list[dict]:
        """List a user's active reminders, soonest first."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM reminders
                    WHERE user_id = %s AND active = true
                    ORDER BY next_fire_at ASC
                    """,
                    (user_id,),
                )
                return cur.fetchall()

    @staticmethod
    def cancel(user_id: int, reminder_id: UUID) -> bool:
        """Deactivate a reminder owned by user_id. Returns True if a row was affected."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE reminders SET active = false
                    WHERE id = %s AND user_id = %s AND active = true
                    """,
                    (reminder_id, user_id),
                )
                applied = cur.rowcount == 1
            conn.commit()
        return applied

    @staticmethod
    def get_due(now: Optional[datetime] = None) -> list[dict]:
        """Return active reminders whose next_fire_at has passed."""
        now = now or datetime.now(timezone.utc)
        conn = get_connection()
        with closing(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT * FROM reminders
                    WHERE active = true AND next_fire_at <= %s
                    ORDER BY next_fire_at ASC
                    """,
                    (now,),
                )
                return cur.fetchall()

    @staticmethod
    def mark_delivered(reminder_id: UUID) -> bool:
        """Deactivate a one-time reminder after delivery."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reminders SET active = false WHERE id = %s",
                    (reminder_id,),
                )
                applied = cur.rowcount == 1
            conn.commit()
        return applied

    @staticmethod
    def reschedule(reminder_id: UUID, next_fire_at: datetime) -> bool:
        """Advance a recurring reminder's next_fire_at, keeping it active."""
        conn = get_connection()
        with closing(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE reminders SET next_fire_at = %s WHERE id = %s AND active = true",
                    (next_fire_at, reminder_id),
                )
                applied = cur.rowcount == 1
            conn.commit()
        return applied


def format_reminder_line(row: dict) -> str:
    """Render a single /reminders list entry."""
    if row["is_recurring"]:
        recurring = "every " + str(row["interval_seconds"]) + "s"
    else:
        recurring = "one-time"
    when = row["next_fire_at"].strftime("%Y-%m-%d %H:%M UTC")
    reminder_id = row["id"]
    message_text = row["message_text"]
    return "#" + str(reminder_id) + " - " + message_text + " (" + recurring + ", next: " + when + ")"


async def delivery_loop(bot, poll_interval_seconds: int = 30) -> None:
    """Poll for due reminders and deliver them, forever, until cancelled.

    On each tick: fetch due reminders, send each via bot.send_message, then either
    mark_delivered (one-time) or reschedule (recurring). A send/storage failure for
    one reminder is logged and does not stop delivery of the rest.
    """
    logger.info("Reminder delivery loop started (poll interval=%ss)", poll_interval_seconds)
    while True:
        try:
            await _deliver_due(bot)
        except Exception as exc:
            logger.error("Reminder delivery poll failed: %s", exc)
        await asyncio.sleep(poll_interval_seconds)


async def _deliver_due(bot) -> None:
    now = datetime.now(timezone.utc)
    due = await asyncio.to_thread(ReminderService.get_due, now)
    for row in due:
        try:
            await bot.send_message(chat_id=row["chat_id"], text="Reminder: " + row["message_text"])
        except Exception as exc:
            logger.error("Failed to deliver reminder %s: %s", row["id"], exc)
            continue
        try:
            if row["is_recurring"]:
                next_fire_at = row["next_fire_at"] + timedelta(seconds=row["interval_seconds"])
                await asyncio.to_thread(ReminderService.reschedule, row["id"], next_fire_at)
            else:
                await asyncio.to_thread(ReminderService.mark_delivered, row["id"])
        except Exception as exc:
            logger.error("Failed to update reminder %s after delivery: %s", row["id"], exc)
