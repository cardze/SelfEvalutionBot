"""Real post-approval full-suite run (design D10): throwaway DB, approved ref only, fresh venv.

Needs Postgres and PyPI access (for the fresh venv); skipped otherwise.
"""

import subprocess
from contextlib import closing
from pathlib import Path

import pytest

import db
from runner import refs, testdb
from runner.config import Config

SUB = "fe11ab1e-0000-0000-0000-000000000000"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

TEST_FILE = '''
import os, psycopg

def test_uses_throwaway_database():
    name = os.environ["POSTGRES_DB"]
    assert name.startswith("feedback_bot_verify_")
    with psycopg.connect(host=os.environ["POSTGRES_HOST"], dbname=name,
                         user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"]) as c:
        assert c.execute("select current_database()").fetchone()[0] == name

def test_no_bot_token():
    assert "TELEGRAM_BOT_TOKEN" not in os.environ
'''


def _db_available():
    try:
        db.init_database()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _databases():
    with closing(db.get_connection()) as conn:
        return {r[0] for r in conn.execute("select datname from pg_database").fetchall()}


@pytest.fixture
def repos(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "requirements.txt").write_text("psycopg==3.1.12\n")
    (main / "tests").mkdir()
    (main / "tests/test_base.py").write_text("def test_base():\n    assert True\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    workspace = tmp_path / "SEB-fe11ab1e"
    subprocess.run(["git", "clone", "-q", str(main), str(workspace)], check=True)
    _git(workspace, "checkout", "-q", "-b", "auto/fe11ab1e")
    config = Config(main=main, workspace_root=tmp_path, bot_python=Path(__import__("sys").executable),
                    runner_home=tmp_path / "rh")
    config.runner_home.mkdir()
    return config, workspace


def test_full_suite_passes_on_throwaway_db(repos, monkeypatch):
    config, workspace = repos
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "must-not-leak")
    (workspace / "tests/test_feature.py").write_text(TEST_FILE)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "feat")
    (workspace / "tests/test_uncommitted.py").write_text("def test_x():\n    assert False\n")  # not approved
    ref = refs.fetch(config, workspace, SUB)
    try:
        result = testdb.run_full_suite(config, ref, SUB)
    except Exception as e:  # e.g. no PyPI access for the fresh venv
        pytest.skip(f"environment not available: {e}")
    if "could not prepare" in result.summary:
        pytest.skip(result.summary)
    assert result.ok, result.summary
    assert result.summary == "3 passed"
    assert testdb.scratch_db_name(SUB) not in _databases()
    assert not (config.runner_home / "verify").exists() or not any((config.runner_home / "verify").iterdir())


def test_full_suite_failure_is_reported(repos):
    config, workspace = repos
    (workspace / "tests/test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "bad")
    ref = refs.fetch(config, workspace, SUB)
    result = testdb.run_full_suite(config, ref, SUB)
    if "could not prepare" in result.summary:
        pytest.skip(result.summary)
    assert not result.ok and "1 failed" in result.summary
    assert testdb.scratch_db_name(SUB) not in _databases()


def test_verdict_rejects_skips():
    assert not testdb.full_suite_verdict(0, "10 passed, 2 skipped in 1.0s").ok
    assert testdb.full_suite_verdict(0, "10 passed in 1.0s").ok
    assert not testdb.full_suite_verdict(1, "1 failed, 9 passed in 1.0s").ok


def test_drop_refuses_other_databases():
    with pytest.raises(ValueError):
        testdb.drop_scratch("feedback_bot")
