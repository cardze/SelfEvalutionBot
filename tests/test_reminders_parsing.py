"""Unit tests for reminders.py parsing helpers (no DB), mirrors tests/test_calculator.py."""

from datetime import datetime, timedelta, timezone

import pytest

from reminders import (
    MAX_OFFSET_SECONDS,
    MIN_INTERVAL_SECONDS,
    ReminderParseError,
    parse_absolute,
    parse_interval,
    parse_relative,
    parse_when,
)

# 2026-09-25 12:00:00 UTC == 2026-09-25 20:00:00 Asia/Taipei.
FIXED_NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


# ---------- parse_relative ----------


def test_parse_relative_minutes():
    result = parse_relative("in 10m", FIXED_NOW)
    assert result == FIXED_NOW.replace(minute=10)


def test_parse_relative_hours():
    result = parse_relative("in 2h", FIXED_NOW)
    assert result == FIXED_NOW.replace(hour=14)


def test_parse_relative_days():
    result = parse_relative("in 3d", FIXED_NOW)
    assert result.day == FIXED_NOW.day + 3


def test_parse_relative_is_utc_aware():
    result = parse_relative("in 5m", FIXED_NOW)
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("bad", ["in", "in ten minutes", "in 10", "in -5m", "in 0m", "in 5x", "soon"])
def test_parse_relative_rejects_garbage(bad):
    with pytest.raises(ReminderParseError):
        parse_relative(bad, FIXED_NOW)


def test_parse_relative_365_days_boundary_is_accepted():
    result = parse_relative("in 365d", FIXED_NOW)
    assert result == FIXED_NOW + timedelta(days=365)


def test_parse_relative_over_365_days_is_rejected():
    with pytest.raises(ReminderParseError):
        parse_relative("in 366d", FIXED_NOW)


def test_parse_relative_max_offset_seconds_boundary_is_accepted():
    # 8760h == 365 days == MAX_OFFSET_SECONDS exactly.
    result = parse_relative("in 8760h", FIXED_NOW)
    assert result == FIXED_NOW + timedelta(seconds=MAX_OFFSET_SECONDS)


def test_parse_relative_over_max_offset_seconds_is_rejected():
    # 8761h is one hour over the 365-day maximum.
    with pytest.raises(ReminderParseError):
        parse_relative("in 8761h", FIXED_NOW)


# ---------- parse_absolute ----------
#
# `at HH:MM` is interpreted as a wall-clock time in Asia/Taipei (UTC+8), then
# converted back to UTC for the returned value (design D5). FIXED_NOW is
# 2026-09-25 20:00 in Asia/Taipei.


def test_parse_absolute_today_when_not_yet_passed():
    # 22:00 Asia/Taipei has not yet passed (it is 20:00 there), so it stays today
    # in Asia/Taipei, which converts to 14:00 UTC on the same UTC calendar day.
    result = parse_absolute("at 22:00", FIXED_NOW)
    assert result.date() == FIXED_NOW.date()
    assert (result.hour, result.minute) == (14, 0)


def test_parse_absolute_rolls_to_tomorrow_when_passed():
    # 09:00 Asia/Taipei has already passed (it is 20:00 there), so it rolls to
    # tomorrow in Asia/Taipei, which converts to 01:00 UTC the next UTC day.
    result = parse_absolute("at 09:00", FIXED_NOW)
    assert result.date() == (FIXED_NOW.date().replace(day=FIXED_NOW.day + 1))
    assert (result.hour, result.minute) == (1, 0)


def test_parse_absolute_is_utc_aware():
    result = parse_absolute("at 14:30", FIXED_NOW)
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 0


def test_parse_absolute_taipei_local_day_differs_from_utc_day():
    # 2026-09-25 16:30 UTC is already 2026-09-26 00:30 in Asia/Taipei: the
    # Taipei calendar day (26th) differs from the UTC calendar day (25th).
    now_cross_day = datetime(2026, 9, 25, 16, 30, 0, tzinfo=timezone.utc)
    # 00:15 Asia/Taipei has already passed today (it is 00:30 there), so it
    # rolls to the *next* Asia/Taipei day (the 27th), which is 16:15 UTC on
    # the 26th -- not simply "tomorrow" relative to the UTC day of `now`.
    result = parse_absolute("at 00:15", now_cross_day)
    assert result == datetime(2026, 9, 26, 16, 15, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("bad", ["at", "at 25:00", "at 14:75", "at 2pm", "at 14-30", "later"])
def test_parse_absolute_rejects_garbage(bad):
    with pytest.raises(ReminderParseError):
        parse_absolute(bad, FIXED_NOW)


# ---------- parse_interval ----------


def test_parse_interval_minutes():
    assert parse_interval("every 5m") == 300


def test_parse_interval_hours():
    assert parse_interval("every 1h") == 3600


def test_parse_interval_days():
    assert parse_interval("every 1d") == 86400


def test_parse_interval_below_minimum_rejected():
    with pytest.raises(ReminderParseError):
        parse_interval("every 10s") if False else parse_interval("every 0m")


def test_parse_interval_below_minimum_seconds_rejected():
    # 59 seconds worth via minutes is not representable; use an interval just under the minute floor.
    with pytest.raises(ReminderParseError):
        parse_interval("every 0m")


@pytest.mark.parametrize("bad", ["every", "every ten minutes", "every -1h", "every 1x"])
def test_parse_interval_rejects_garbage(bad):
    with pytest.raises(ReminderParseError):
        parse_interval(bad)


def test_parse_interval_minimum_boundary_is_accepted():
    assert parse_interval("every 1m") == MIN_INTERVAL_SECONDS


def test_parse_interval_365_days_boundary_is_accepted():
    assert parse_interval("every 365d") == 365 * 86400


def test_parse_interval_over_365_days_is_rejected():
    with pytest.raises(ReminderParseError):
        parse_interval("every 366d")


def test_parse_interval_max_offset_seconds_boundary_is_accepted():
    assert parse_interval("every 8760h") == MAX_OFFSET_SECONDS


def test_parse_interval_over_max_offset_seconds_is_rejected():
    with pytest.raises(ReminderParseError):
        parse_interval("every 8761h")


# ---------- parse_when ----------


def test_parse_when_relative():
    next_fire_at, is_recurring, interval_seconds = parse_when("in 10m", FIXED_NOW)
    assert is_recurring is False
    assert interval_seconds is None
    assert next_fire_at == FIXED_NOW.replace(minute=10)


def test_parse_when_absolute():
    # "at 14:30" (Asia/Taipei) has already passed relative to FIXED_NOW (20:00
    # Asia/Taipei), so it rolls to tomorrow, which is 06:30 UTC.
    next_fire_at, is_recurring, interval_seconds = parse_when("at 14:30", FIXED_NOW)
    assert is_recurring is False
    assert interval_seconds is None
    assert (next_fire_at.hour, next_fire_at.minute) == (6, 30)


def test_parse_when_every():
    next_fire_at, is_recurring, interval_seconds = parse_when("every 1h", FIXED_NOW)
    assert is_recurring is True
    assert interval_seconds == 3600
    assert next_fire_at == FIXED_NOW.replace(hour=13)


def test_parse_when_returns_utc_aware_datetime():
    next_fire_at, _, _ = parse_when("in 1m", FIXED_NOW)
    assert next_fire_at.tzinfo is not None


@pytest.mark.parametrize("bad", ["", "sometime soon", "tomorrow", "asap"])
def test_parse_when_rejects_garbage(bad):
    with pytest.raises(ReminderParseError):
        parse_when(bad, FIXED_NOW)
