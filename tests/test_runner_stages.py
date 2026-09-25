"""Stage-machine tests for runner/runner.py (design D4, D8).

DB-backed (skipped without Postgres) with real git on temporary repos. Claude runs, Telegram,
the self-test, sandboxed verification, the test-DB reset, openspec/pip/launchctl are faked.
"""

import dataclasses
import json
import shutil
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

import db
from runner import agent, notify, selftest, snapshot, testdb, verify
from runner import runner as rr
from runner import workspace as ws
from runner.config import Config
from storage import FeedbackService

TEST_USER_ID = -535353
REPO = Path(__file__).resolve().parent.parent
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _db_available():
    try:
        db.init_database()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="PostgreSQL not available")


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def _cleanup():
    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM feedback_events WHERE user_id = %s", (TEST_USER_ID,))
            cur.execute("DELETE FROM feedback_submissions WHERE user_id = %s", (TEST_USER_ID,))
        conn.commit()


class Env:
    """Wires fakes and records what happened."""

    def __init__(self, config):
        self.config = config
        self.notes = []            # (kind, payload)
        self.agent_prompts = []    # stage names in order
        self.inputs = []           # input.json seen by the fake agent
        self.verify_ok = True
        self.selftest_ok = True
        self.plan_output = True
        self.full_ok = True


@pytest.fixture
def env(tmp_path, monkeypatch):
    if FeedbackService.get_inflight_auto_run() is not None:
        pytest.skip("a real autonomous run is in flight")
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("ADMIN_USER_ID", str(TEST_USER_ID))
    _cleanup()

    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    shutil.copytree(REPO / "runner/prompts", main / "runner/prompts")
    (main / "requirements.txt").write_text("psycopg==3.1.12\n")
    (main / "openspec/changes/archive").mkdir(parents=True)
    (main / "openspec/changes/archive/.keep").write_text("")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")

    config = Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
                    runner_home=tmp_path / "rh", snapshot_home=tmp_path / "snap")
    config.runner_home.mkdir()
    e = Env(config)

    # --- fakes ---
    monkeypatch.setattr(ws, "setup_venv", lambda c, p: None)
    monkeypatch.setattr(rr, "read_token", lambda c: "sk-ant-oat01-fake")
    monkeypatch.setattr(snapshot, "agents_json", lambda c: "{}")
    monkeypatch.setattr(snapshot, "export_skills", lambda c: None)
    monkeypatch.setattr(selftest, "run", lambda c, cwd, t: (e.selftest_ok, ["fake self-test"]))
    monkeypatch.setattr(verify, "run", lambda c, p, t: verify.Verification(e.verify_ok, "3 passed" if e.verify_ok else "1 failed"))
    monkeypatch.setattr(testdb, "run_full_suite",
                        lambda c, ref, sub: verify.Verification(e.full_ok, "5 passed" if e.full_ok else "1 failed"))

    def fake_agent(config, path, prompt, limits, *, token, agents_json):
        data = json.loads((path / ".auto/input.json").read_text())
        e.inputs.append(data)
        if "stage: PLAN" in prompt:
            e.agent_prompts.append("plan")
            if e.plan_output:
                (path / "openspec/changes/add-x").mkdir(parents=True, exist_ok=True)
                (path / "openspec/changes/add-x/proposal.md").write_text("why")
                (path / "openspec/changes/add-x/tasks.md").write_text("- [ ] 1.1 build it\n")
                _git(path, "add", "openspec")
                _git(path, "commit", "-q", "-m", "docs: propose add-x")
                (path / ".auto/output.json").write_text(json.dumps(
                    {"stage": "planned", "change_name": "add-x", "summary": "Plan summary"}))
        else:
            e.agent_prompts.append("build")
            n = len(e.agent_prompts)
            (path / f"feature_{n}.py").write_text(f"X = {n}\n")
            _git(path, "add", "-A", ".")
            _git(path, "reset", "-q", ".auto")  # never commit runner I/O
            _git(path, "commit", "-q", "-m", f"feat {n}")
            (path / ".auto/output.json").write_text(json.dumps({"stage": "built", "summary": "Built it"}))
        return agent.AgentResult(True, "done", 0.1, False, "")

    monkeypatch.setattr(agent, "run", fake_agent)

    for kind in ("planned", "merge_request", "failure", "warning", "merged", "rejected"):
        monkeypatch.setattr(notify, kind, (lambda k: lambda *a, **kw: e.notes.append((k, a)))(kind))

    real_run = subprocess.run

    def fake_subprocess(cmd, *args, **kwargs):
        if cmd[0] == "openspec" and cmd[1] == "archive":
            name = cmd[2]
            src = config.main / "openspec/changes" / name
            shutil.move(str(src), str(config.main / "openspec/changes/archive" / f"2026-01-01-{name}"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if cmd[0] == "launchctl" or (len(cmd) > 2 and cmd[1:3] == ["-m", "pip"]):
            e.notes.append(("exec", cmd[0] if cmd[0] == "launchctl" else "pip"))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(rr.subprocess, "run", fake_subprocess)
    yield e
    run = FeedbackService.get_inflight_auto_run()
    _cleanup()  # cascades to auto_runs


def kinds(e):
    return [k for k, _ in e.notes]


def new_submission(text="I want reminders"):
    return FeedbackService.store_submission(TEST_USER_ID, text, "please")


def run_row(sub):
    run = FeedbackService.get_inflight_auto_run()
    assert run is None or str(run["feedback_submission_id"]) == str(sub)
    return run


# ---------- tests ----------


def test_idle_and_throttle(env):
    assert rr.tick(env.config) == "idle"
    new_submission()
    rr.mark_last_run(env.config, time.time())
    assert rr.tick(env.config) == "throttled"
    assert env.agent_prompts == []


def test_straight_through_to_merge_request(env):
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
    assert env.agent_prompts == ["plan", "build"]
    assert kinds(env) == ["planned", "merge_request"]
    run = run_row(sub)
    assert (run["stage"], run["change_name"]) == ("awaiting_decision", "add-x")
    assert Path(run["workspace_path"]).exists()
    # submission is hidden from the queue while in flight
    assert FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID)["actionable"] == []
    # waiting: nothing happens until a decision
    assert rr.tick(env.config) == "waiting"


def test_merge_path(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    rr.mark_last_run(env.config, time.time())  # decisions are processed regardless of throttle
    assert FeedbackService.set_auto_run_decision(run["id"], "merge")
    assert rr.tick(env.config) == "merged"
    main = env.config.main
    log = subprocess.run(["git", "-C", str(main), "log", "--oneline", "-3"], capture_output=True, text=True).stdout
    assert "archive add-x" in log and "Merge runner change add-x" in log
    assert (main / "openspec/changes/archive/2026-01-01-add-x/tasks.md").exists()
    assert (main / "feature_2.py").exists()
    assert not Path(run["workspace_path"]).exists()
    assert FeedbackService.get_auto_run(run["id"])["stage"] == "merged"
    assert ("exec", "launchctl") in env.notes and ("exec", "pip") in env.notes
    assert "merged" in kinds(env)
    assert sub not in [r["id"] for r in FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID)["actionable"]]


def test_merge_waits_for_dirty_main(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    FeedbackService.set_auto_run_decision(run["id"], "merge")
    (env.config.main / "requirements.txt").write_text("dirty\n")
    assert rr.tick(env.config) == "merge_waiting"
    assert rr.tick(env.config) == "merge_waiting"
    assert kinds(env).count("warning") == 1  # not repeated every hour


def test_reject_path(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    FeedbackService.set_auto_run_decision(run["id"], "reject", "Not worth it")
    assert rr.tick(env.config) == "rejected"
    archived = list((env.config.main / "openspec/changes/archive").glob("*-add-x"))
    assert len(archived) == 1 and "Not worth it" in (archived[0] / "REJECTED.md").read_text()
    assert not Path(run["workspace_path"]).exists()
    assert FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID)["actionable"] == []  # wont_do
    assert "rejected" in kinds(env)


def test_changes_path_passes_note(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    FeedbackService.set_auto_run_decision(run["id"], "changes", "use relative times only")
    assert rr.tick(env.config) == "awaiting_decision"
    assert env.agent_prompts == ["plan", "build", "build"]
    assert env.inputs[-1]["admin_note"] == "use relative times only"
    assert kinds(env).count("merge_request") == 2


def test_build_failure_escalates(env):
    env.verify_ok = False
    sub = new_submission()
    assert rr.tick(env.config) == "retry"
    assert run_row(sub)["stage"] == "building"
    assert rr.tick(env.config) == "failed"
    assert run_row(sub)["stage"] == "failed"
    assert kinds(env)[-1] == "failure"


def test_resume_from_planned(env):
    sub = new_submission()
    env.verify_ok = False
    rr.tick(env.config)                 # plan ok, build retry
    env.verify_ok = True
    FeedbackService.update_auto_run(run_row(sub)["id"], stage="planned")
    assert rr.tick(env.config) == "awaiting_decision"
    assert env.agent_prompts.count("plan") == 1


def test_isolation_failure_stops_before_agent(env):
    env.selftest_ok = False
    sub = new_submission()
    assert rr.tick(env.config) == "failed"
    assert env.agent_prompts == []
    assert "Isolation self-test failed" in run_row(sub)["last_error"]


def test_missing_plan_output_fails(env):
    env.plan_output = False
    sub = new_submission()
    assert rr.tick(env.config) == "failed"
    assert env.agent_prompts == ["plan"]
    assert "PLAN failed" in run_row(sub)["last_error"]


def test_full_suite_failure_aborts_merge(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    FeedbackService.set_auto_run_decision(run["id"], "merge")
    env.full_ok = False
    assert rr.tick(env.config) == "merge_aborted"
    row = FeedbackService.get_auto_run(run["id"])
    assert row["stage"] == "awaiting_decision" and row["decision"] is None
    assert "Merge runner change" not in subprocess.run(
        ["git", "-C", str(env.config.main), "log", "--oneline"], capture_output=True, text=True).stdout
    assert kinds(env)[-1] == "failure"
