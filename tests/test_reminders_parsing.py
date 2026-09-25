"""Unit tests for reminders.py parsing helpers (no DB), mirrors tests/test_calculator.py."""

from datetime import datetime, timezone

import pytest

from reminders import (
    MIN_INTERVAL_SECONDS,
    ReminderParseError,
    parse_absolute,
    parse_interval,
    parse_relative,
    parse_when,
)

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


# ---------- parse_absolute ----------


def test_parse_absolute_today_when_not_yet_passed():
    result = parse_absolute("at 14:30", FIXED_NOW)
    assert result.date() == FIXED_NOW.date()
    assert (result.hour, result.minute) == (14, 30)


def test_parse_absolute_rolls_to_tomorrow_when_passed():
    result = parse_absolute("at 09:00", FIXED_NOW)
    assert result.date() == (FIXED_NOW.date().replace(day=FIXED_NOW.day + 1))
    assert (result.hour, result.minute) == (9, 0)


def test_parse_absolute_is_utc_aware():
    result = parse_absolute("at 14:30", FIXED_NOW)
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 0


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
    # 59 seconds worth via minutes isn't representable; use an interval just under the minute floor.
    with pytest.raises(ReminderParseError):
        parse_interval("every 0m")


@pytest.mark.parametrize("bad", ["every", "every ten minutes", "every -1h", "every 1x"])
def test_parse_interval_rejects_garbage(bad):
    with pytest.raises(ReminderParseError):
        parse_interval(bad)


def test_parse_interval_minimum_boundary_is_accepted():
    assert parse_interval("every 1m") == MIN_INTERVAL_SECONDS


# ---------- parse_when ----------


def test_parse_when_relative():
    next_fire_at, is_recurring, interval_seconds = parse_when("in 10m", FIXED_NOW)
    assert is_recurring is False
    assert interval_seconds is None
    assert next_fire_at == FIXED_NOW.replace(minute=10)


def test_parse_when_absolute():
    next_fire_at, is_recurring, interval_seconds = parse_when("at 14:30", FIXED_NOW)
    assert is_recurring is False
    assert interval_seconds is None
    assert (next_fire_at.hour, next_fire_at.minute) == (14, 30)


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
