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
        self.reviews = []          # reviewers named in each REVIEW prompt
        self.review_says = {}      # reviewer → "CHANGES" (default PASS)
        self.review_fix = ""       # path the REVIEW fix round commits, when any reviewer says CHANGES


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
        elif "stage: REVIEW" in prompt:
            names = [n for n in ("code", "security", "ux", "ui") if f"`review-{n}`" in prompt]
            e.reviews.append(names)
            (path / ".auto/review").mkdir(parents=True, exist_ok=True)
            for n in names:
                (path / f".auto/review/review-{n}.md").write_text(
                    f"VERDICT: {e.review_says.get(n, 'PASS')}\n- finding from {n}\n")
            if "CHANGES" in [e.review_says.get(n) for n in names] and e.review_fix:
                (path / e.review_fix).parent.mkdir(parents=True, exist_ok=True)
                (path / e.review_fix).write_text("FIXED = True\n")
                _git(path, "add", e.review_fix)
                _git(path, "commit", "-q", "-m", "fix: address review findings")
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
    e.archive_refuses = False

    def fake_scan(config, now):
        if e.scan_error:
            raise e.scan_error
        return {"read": 0, "dropped": 0, "suggested": 0, "reset": 0, "dismissed": 0}

    monkeypatch.setattr(rr.signals, "scan", fake_scan)

    real_run = subprocess.run

    def fake_subprocess(cmd, *args, **kwargs):
        e.commands.append(list(cmd))
        if cmd[0] == "openspec" and cmd[1] == "archive":
            if e.archive_refuses:  # real openspec exits 0 when it aborts on an invalid spec
                return subprocess.CompletedProcess(cmd, 0, "Aborted. No files were changed.", "")
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
    # The runner settings are rendered from the current template on every tick.
    settings = json.loads(env.config.settings_file.read_text())
    assert f"{Path.home()}/.hermes" in settings["sandbox"]["filesystem"]["denyRead"]
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


def test_merge_still_finishes_when_openspec_refuses_to_archive(env):
    sub = new_submission()
    rr.tick(env.config)
    run = run_row(sub)
    env.archive_refuses = True
    assert FeedbackService.set_auto_run_decision(run["id"], "merge")
    assert rr.tick(env.config) == "merged"
    assert (env.config.main / "openspec/changes/add-x").exists()
    assert FeedbackService.get_auto_run(run["id"])["stage"] == "merged"
    [warning] = [n for n in env.notes if n[0] == "warning"]
    assert "did not archive" in warning[1][0] and "Aborted" in warning[1][0]


def test_merge_path_hermes_restarts_gateway_after_merged(env, monkeypatch):
    """move-bot-into-hermes B5: no launchctl; the gateway restart is detached and comes last."""
    env.config = dataclasses.replace(env.config, bot_service="hermes", hermes_profile="seb",
                                     hermes_bin="/opt/hermes/bin/hermes")
    spawned = []
    synced = []
    real_popen = subprocess.Popen
    faked_run = rr.subprocess.run

    def fake_popen(cmd, *args, **kwargs):
        if "gateway" not in cmd:
            return real_popen(cmd, *args, **kwargs)
        run = FeedbackService.get_auto_run(run_id)
        spawned.append((cmd, kwargs, run["stage"], kinds(env)[:]))

    def fake_run(cmd, *args, **kwargs):
        if str(cmd[0]).endswith("hermes_profile/setup.sh"):
            synced.append((cmd, kwargs["env"]))
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return faked_run(cmd, *args, **kwargs)

    monkeypatch.setattr(rr.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(rr.subprocess, "run", fake_run)
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision", env.notes
    run_id = run_row(sub)["id"]
    FeedbackService.set_auto_run_decision(run_id, "merge")
    assert rr.tick(env.config) == "merged"

    assert ("exec", "launchctl") not in env.notes
    pips = [c for c in env.commands if c[1:3] == ["-m", "pip"]]
    assert [c[0] for c in pips] == ["/usr/bin/python3"]  # Hermes's own environment is never pip-installed
    assert synced == []  # guard-hermes-from-runner G4: a merge never runs setup.sh
    assert not [c for c in env.commands if "hermes" in Path(str(c[0])).name or "setup.sh" in str(c[0])]
    [(cmd, kwargs, stage, notes_then)] = spawned
    assert cmd[-5:] == ["/opt/hermes/bin/hermes", "-p", "seb", "gateway", "restart"]
    assert kwargs["start_new_session"] is True
    assert stage == "merged" and "merged" in notes_then
    assert "warning" not in kinds(env)


def test_build_touching_hermes_plugin_fails_without_retry(env, monkeypatch):
    """guard-hermes-from-runner: refused after BUILD, no retry, no merge request."""
    real_agent = agent.run

    def plugin_agent(config, path, prompt, limits, *, token, agents_json):
        result = real_agent(config, path, prompt, limits, token=token, agents_json=agents_json)
        if "stage: BUILD" in prompt:
            (path / "hermes_plugin/seb").mkdir(parents=True)
            (path / "hermes_plugin/seb/__init__.py").write_text("def register(ctx): pass\n")
            _git(path, "add", "hermes_plugin")
            _git(path, "commit", "-q", "-m", "touch plugin")
        return result

    monkeypatch.setattr(agent, "run", plugin_agent)
    sub = new_submission()
    assert rr.tick(env.config) == "failed"
    assert env.agent_prompts == ["plan", "build"]
    assert kinds(env) == ["planned", "failure"]
    message = env.notes[-1][1][1]
    assert "BUILD refused" in message and "hermes_plugin/seb/__init__.py" in message
    assert FeedbackService.get_auto_run(run_id_of(sub))["stage"] == "failed"


def test_merge_refuses_protected_commit(env):
    """The ref is re-checked before merging: the workspace is agent-controlled."""
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
    run = run_row(sub)
    path = Path(run["workspace_path"])
    (path / "hermes_bot.py").write_text("x = 1\n")
    _git(path, "add", "hermes_bot.py")
    _git(path, "commit", "-q", "-m", "sneak in")
    head = subprocess.run(["git", "-C", str(env.config.main), "rev-parse", "main"],
                          capture_output=True, text=True).stdout
    FeedbackService.set_auto_run_decision(run["id"], "merge")
    assert rr.tick(env.config) == "merge_aborted"
    assert subprocess.run(["git", "-C", str(env.config.main), "rev-parse", "main"],
                          capture_output=True, text=True).stdout == head
    assert "Merge refused" in env.notes[-1][1][1] and "hermes_bot.py" in env.notes[-1][1][1]
    after = FeedbackService.get_auto_run(run["id"])
    assert after["stage"] == "awaiting_decision" and after["decision"] is None


def run_id_of(sub):
    conn = db.get_connection()
    with closing(conn):
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM auto_runs WHERE feedback_submission_id = %s", (sub,))
            row = cur.fetchone()
            return row["id"] if isinstance(row, dict) else row[0]


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


# ---------- REVIEW step (add-runner-review-step) ----------


def test_review_runs_after_build_and_reaches_the_merge_request(env):
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
    assert env.reviews == [["code", "security"]]  # the fake build changes no bot messages
    verdicts = run_row(sub)["review_verdicts"]
    assert {n: v["verdict"] for n, v in verdicts.items()} == {
        "code": "PASS", "security": "PASS", "ux": "SKIPPED", "ui": "SKIPPED"}
    assert "finding from code" in verdicts["code"]["findings"]
    review_line = env.notes[-1][1][-1]
    assert review_line.startswith("Review: code ✅ · security ✅") and "ux, ui not run" in review_line


def test_review_fix_is_retested_and_shown_as_fixed(env, monkeypatch):
    env.review_says = {"security": "CHANGES"}
    env.review_fix = "feature_fix.py"
    calls = []
    monkeypatch.setattr(verify, "run", lambda c, p, t: calls.append(p) or verify.Verification(True, "3 passed"))
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
    assert len(calls) == 2  # after BUILD, and again after the fix round
    assert run_row(sub)["review_verdicts"]["security"]["verdict"] == "FIXED"
    assert "security 🔧 fixed" in env.notes[-1][1][-1]
    # The review branch points at the fixed commit, not the one BUILD made.
    assert "feature_fix.py" in refs.changed_paths(env.config, refs.ref_name(sub))


def test_unfixed_changes_still_reach_the_admin(env):
    env.review_says = {"code": "CHANGES"}
    sub = new_submission()
    assert rr.tick(env.config) == "awaiting_decision"
    assert run_row(sub)["review_verdicts"]["code"]["verdict"] == "CHANGES"
    assert "code ⚠️ changes not fixed" in env.notes[-1][1][-1]


def test_failing_tests_after_the_fix_round_count_as_a_failed_build(env, monkeypatch):
    env.review_says = {"code": "CHANGES"}
    env.review_fix = "feature_fix.py"
    results = iter([True, False])
    monkeypatch.setattr(verify, "run", lambda c, p, t: verify.Verification(next(results), "1 failed"))
    sub = new_submission()
    assert rr.tick(env.config) == "retry"
    run = run_row(sub)
    assert run["stage"] == "building" and "after the review fixes" in run["last_error"]


def test_review_fix_touching_hermes_is_refused(env):
    env.review_says = {"security": "CHANGES"}
    env.review_fix = "hermes_plugin/seb/__init__.py"
    sub = new_submission()
    assert rr.tick(env.config) == "failed"
    assert "REVIEW fix refused" in env.notes[-1][1][1]
    assert run_row(sub)["stage"] == "failed"
