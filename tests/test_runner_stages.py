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
from runner import agent, notify, refs, selftest, snapshot, testdb, verify
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
            cur.execute("DELETE FROM runner_signals WHERE fingerprint LIKE 'test-stage:%%'")
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
        self.commands = []         # every subprocess command run while faked


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
                    {"stage": "planned", "change_name": "add-x", "summary": "Plan summary",
                     "impact": {"changes": "feature_N.py", "risk": "none", "size": "small"}}))
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

    for kind in ("planned", "merge_request", "failure", "warning", "merged", "rejected", "signal"):
        # Each fake returns a message id, like the real ones.
        monkeypatch.setattr(notify, kind, (lambda k: lambda *a, **kw: e.notes.append((k, a, kw)) or 1)(kind))
    # The signal scan reads the real runner_signals table; stage tests replace it (tested on its own).
    e.scan_error = None

    def fake_scan(config, now):
        if e.scan_error:
            raise e.scan_error
        return {"read": 0, "dropped": 0, "suggested": 0, "reset": 0, "dismissed": 0}

    monkeypatch.setattr(rr.signals, "scan", fake_scan)

    real_run = subprocess.run

    def fake_subprocess(cmd, *args, **kwargs):
        e.commands.append(list(cmd))
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
    # The runner never pushes anything anywhere (runner-review: review branches are never pushed).
    assert not [c for c in e.commands if "push" in c], "runner invoked git push"


def kinds(e):
    return [n[0] for n in e.notes]


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


def test_merge_path_hermes_restarts_gateway_after_merged(env, monkeypatch):
    """move-bot-into-hermes B5: no launchctl; the gateway restart is detached and comes last."""
    env.config = dataclasses.replace(env.config, bot_service="hermes", hermes_profile="seb",
                                     hermes_python=Path("/opt/hermes/bin/python"), hermes_bin="/bin/hermes")
    (env.config.main / "requirements.txt").write_text("python-telegram-bot==20.7\npsycopg==3.1.12\n")
    _git(env.config.main, "commit", "-q", "-am", "reqs")
    spawned = []
    real_popen = subprocess.Popen

    def fake_popen(cmd, *args, **kwargs):
        if "gateway" not in cmd:
            return real_popen(cmd, *args, **kwargs)
        run = FeedbackService.get_auto_run(run_id)
        spawned.append((cmd, kwargs, run["stage"], kinds(env)[:]))

    monkeypatch.setattr(rr.subprocess, "Popen", fake_popen)
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision", env.notes
    run_id = run_row(sub)["id"]
    FeedbackService.set_auto_run_decision(run_id, "merge")
    assert rr.tick(env.config) == "merged"

    assert ("exec", "launchctl") not in env.notes
    pips = [c for c in env.commands if c[1:3] == ["-m", "pip"]]
    assert [c[0] for c in pips] == ["/usr/bin/python3", "/opt/hermes/bin/python"]
    filtered = Path(pips[1][-1]).read_text()
    assert "python-telegram-bot" not in filtered and "psycopg==3.1.12" in filtered
    [(cmd, kwargs, stage, notes_then)] = spawned
    assert cmd[-5:] == ["/bin/hermes", "-p", "seb", "gateway", "restart"]
    assert kwargs["start_new_session"] is True
    assert stage == "merged" and "merged" in notes_then
    assert "warning" not in kinds(env)


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


# ---------- review branch (add-runner-review-branch) ----------


def _rev(e, name):
    return subprocess.run(["git", "-C", str(e.config.main), "rev-parse", "--verify", "-q", name],
                          capture_output=True, text=True).stdout.strip()


def test_review_branch_matches_merge_request(env):
    sub = new_submission()
    rr.tick(env.config)
    assert _rev(env, "review/add-x") == _rev(env, refs.ref_name(sub)) != ""
    assert "diff main...review/add-x" in env.notes[-1][1][6]


def test_stale_review_branch_is_overwritten(env):
    _git(env.config.main, "branch", "review/add-x", "main")
    sub = new_submission()
    rr.tick(env.config)
    assert _rev(env, "review/add-x") == _rev(env, refs.ref_name(sub))


def test_changes_path_moves_review_branch(env):
    sub = new_submission()
    rr.tick(env.config)
    first = _rev(env, "review/add-x")
    run = run_row(sub)
    FeedbackService.set_auto_run_decision(run["id"], "changes", "again")
    env.verify_ok = False
    assert rr.tick(env.config) == "retry"
    assert _rev(env, "review/add-x") == ""          # dropped at BUILD start, not recreated
    env.verify_ok = True
    assert rr.tick(env.config) == "awaiting_decision"
    second = _rev(env, "review/add-x")
    assert second not in ("", first) and second == _rev(env, refs.ref_name(sub))


def test_no_review_branch_when_build_fails(env):
    env.verify_ok = False
    new_submission()
    rr.tick(env.config)
    assert _rev(env, "review/add-x") == ""


def test_merge_deletes_review_branch(env):
    sub = new_submission()
    rr.tick(env.config)
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "merge")
    assert rr.tick(env.config) == "merged"
    assert _rev(env, "review/add-x") == "" and _rev(env, refs.ref_name(sub)) == ""


def test_merge_abort_keeps_review_branch(env):
    sub = new_submission()
    rr.tick(env.config)
    before = _rev(env, "review/add-x")
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "merge")
    env.full_ok = False
    assert rr.tick(env.config) == "merge_aborted"
    assert _rev(env, "review/add-x") == before != ""


def test_reject_deletes_review_branch(env):
    sub = new_submission()
    rr.tick(env.config)
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "reject")
    assert rr.tick(env.config) == "rejected"
    assert _rev(env, "review/add-x") == ""


def test_reject_off_main_still_deletes_review_branch(env):
    sub = new_submission()
    rr.tick(env.config)
    _git(env.config.main, "checkout", "-q", "-b", "elsewhere")
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "reject")
    assert rr.tick(env.config) == "rejected"
    assert _rev(env, "review/add-x") == ""


def test_reject_after_failed_plan(env):
    env.plan_output = False
    sub = new_submission()
    assert rr.tick(env.config) == "failed"
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "reject")
    assert rr.tick(env.config) == "rejected"


def test_checked_out_review_branch_is_left_alone(env):
    sub = new_submission()
    rr.tick(env.config)
    before = _rev(env, "review/add-x")
    _git(env.config.main, "checkout", "-q", "review/add-x")
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "changes", "again")
    assert rr.tick(env.config) == "awaiting_decision"
    assert _rev(env, "review/add-x") == before
    warnings = [n[1][0] for n in env.notes if n[0] == "warning"]
    assert warnings and all("review/add-x is checked out" in w for w in warnings)


# ---------- held plans for runner-suggested work (add-runner-signals) ----------


def gated_submission():
    """A submission created from an accepted runner signal, as 📋 Plan a fix would make it."""
    sub = new_submission("💡 /meal sometimes fails for users")
    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runner_signals (fingerprint, kind, exc, occurrences, first_seen, last_seen,
                                            status, feedback_submission_id)
                VALUES ('test-stage:gate', 'unhandled', 'KeyError', 1, now(), now(), 'accepted', %s)
                """,
                (sub,),
            )
        conn.commit()
    return sub


def planned_notes(e):
    return [n for n in e.notes if n[0] == "planned"]


def test_impact_is_shown_for_ordinary_runs(env):
    new_submission()
    rr.tick(env.config)
    [(_, args, kwargs)] = planned_notes(env)
    assert args[3] == {"changes": "feature_N.py", "risk": "none", "size": "small"}
    assert not kwargs.get("gated")


def test_gated_run_stops_after_plan(env):
    sub = gated_submission()
    assert rr.tick(env.config) == "waiting"
    assert env.agent_prompts == ["plan"]
    [(_, args, kwargs)] = planned_notes(env)
    assert kwargs["gated"] is True and args[3]["size"] == "small"
    run = run_row(sub)
    assert run["stage"] == "planned" and run["plan_message_id"] == 1
    assert rr.tick(env.config) == "waiting"     # nothing happens until a decision
    assert env.agent_prompts == ["plan"] and len(planned_notes(env)) == 1


def test_lost_plan_message_is_resent(env):
    sub = gated_submission()
    rr.tick(env.config)
    FeedbackService.update_auto_run(run_row(sub)["id"], plan_message_id=None)
    assert rr.tick(env.config) == "waiting"
    assert len(planned_notes(env)) == 2 and planned_notes(env)[1][2]["gated"] is True
    assert run_row(sub)["plan_message_id"] == 1


def test_build_tap_builds(env):
    sub = gated_submission()
    rr.tick(env.config)
    assert FeedbackService.set_auto_run_decision(run_row(sub)["id"], "build")
    assert rr.tick(env.config) == "awaiting_decision"
    assert env.agent_prompts == ["plan", "build"]
    run = run_row(sub)
    assert run["decision"] is None and kinds(env)[-1] == "merge_request"


def test_drop_tap_rejects(env):
    sub = gated_submission()
    rr.tick(env.config)
    assert FeedbackService.set_auto_run_decision(run_row(sub)["id"], "reject", "not worth it")
    assert rr.tick(env.config) == "rejected"
    assert env.agent_prompts == ["plan"]
    archived = list((env.config.main / "openspec/changes/archive").glob("*-add-x"))
    assert len(archived) == 1 and "not worth it" in (archived[0] / "REJECTED.md").read_text()
    assert FeedbackService.get_actionable_feedback(user_id=TEST_USER_ID)["actionable"] == []


def test_failed_gated_plan_replans_and_stops_again(env):
    env.plan_output = False
    sub = gated_submission()
    assert rr.tick(env.config) == "failed"
    FeedbackService.set_auto_run_decision(run_row(sub)["id"], "changes", "try again")
    env.plan_output = True
    assert rr.tick(env.config) == "waiting"
    assert run_row(sub)["stage"] == "planned" and env.agent_prompts == ["plan", "plan"]


def test_scan_failure_does_not_block_work(env):
    env.scan_error = RuntimeError("events file is broken")
    new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
