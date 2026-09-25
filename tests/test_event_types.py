"""EVENT_TYPES in storage.py must match the CHECK constraint in sql/init.sql."""

import os
import re

from storage import EVENT_TYPES

INIT_SQL = os.path.join(os.path.dirname(__file__), "..", "sql", "init.sql")


def _event_types_from_init_sql():
    with open(INIT_SQL) as f:
        sql = f.read()
    match = re.search(
        r"feedback_events_event_type_check\s+CHECK\s*\(\s*event_type\s+IN\s*\(([^)]*)\)",
        sql,
        re.IGNORECASE,
    )
    assert match, "feedback_events_event_type_check not found in sql/init.sql"
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_event_types_match_init_sql():
    assert set(EVENT_TYPES) == _event_types_from_init_sql()


def test_event_types_fit_column():
    assert all(len(t) <= 50 for t in EVENT_TYPES)
