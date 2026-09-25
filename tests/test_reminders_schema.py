"""Static checks on sql/init.sql for the reminders table, mirrors tests/test_event_types.py."""

import os
import re

from reminders import MIN_INTERVAL_SECONDS

INIT_SQL = os.path.join(os.path.dirname(__file__), "..", "sql", "init.sql")


def _read_init_sql():
    with open(INIT_SQL) as f:
        return f.read()


def test_reminders_table_exists():
    sql = _read_init_sql()
    assert re.search(r"CREATE TABLE IF NOT EXISTS reminders\s*\(", sql, re.IGNORECASE)


def test_reminders_active_next_fire_at_index_exists():
    sql = _read_init_sql()
    match = re.search(
        r"CREATE INDEX IF NOT EXISTS idx_reminders_active_next_fire_at\s+"
        r"ON reminders\(active,\s*next_fire_at\)",
        sql,
        re.IGNORECASE,
    )
    assert match, "expected an (active, next_fire_at) index on reminders"


def test_reminders_interval_check_matches_min_interval_constant():
    sql = _read_init_sql()
    match = re.search(
        r"reminders_interval_seconds_check\s+CHECK\s*\(.*?interval_seconds\s*>=\s*(\d+)",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match, "reminders_interval_seconds_check not found in sql/init.sql"
    assert int(match.group(1)) == MIN_INTERVAL_SECONDS


def test_reminders_id_uses_uuid_default():
    sql = _read_init_sql()
    table_match = re.search(
        r"CREATE TABLE IF NOT EXISTS reminders\s*\((.*?)\);",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert table_match
    assert re.search(r"id\s+UUID\s+PRIMARY KEY\s+DEFAULT\s+gen_random_uuid\(\)", table_match.group(1), re.IGNORECASE)
