"""One tick of the autonomous feedback runner (design D4). Started hourly by runner/run.sh.

    decisions → resume in-flight run → throttle → pick admin feedback → PLAN → 📋 → BUILD → verify → 🔀

Everything with side effects outside the workspace (Telegram, merge, archive, resolve, bot restart)
happens here, in the trusted process. Agents only ever run sandboxed (runner/agent.py) after a
passing isolation self-test (runner/selftest.py).
"""

import logging
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from clarify import get_admin_user_id
from runner import agent, notify, refs, selftest, snapshot, testdb, validate, verify
from runner import workspace as ws
from runner.config import Config, load_config, load_main_secrets, read_token
from storage import ClarificationError, FeedbackService

log = logging.getLogger("runner")


class IsolationError(Exception):
    """The self-test found the sandbox leaking; no agent may start."""


class Session:
    """Per-tick lazily loaded secrets/snapshot, and at most one self-test per tick."""

    def __init__(self, config: Config):
        self.config = config
        self._loaded = False
        self._selftest_passed = False

    def _load(self):
        if not self._loaded:
            self.token = read_token(self.config)
            self.agents_json = snapshot.agents_json(self.config)
            snapshot.export_skills(self.config)
            self._loaded = True

    def ensure_ready(self, workspace: Path) -> None:
        self._load()
        if not self._selftest_passed:
            ok, report = selftest.run(self.config, workspace, self.token)
            log.info("self-test: %s", "; ".join(report))
            if not ok:
                raise IsolationError("\n".join(report))
            self._selftest_passed = True


# ---------- helpers ----------


def render_prompt(config: Config, name: str, **values) -> str:
    text = (config.main / "runner/prompts" / name).read_text()
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def throttle_ok(config: Config, now: float) -> bool:
    try:
        last = float(config.last_run_file.read_text().strip())
    except (OSError, ValueError):
        return True
    return now - last >= config.throttle_hours * 3600


def mark_last_run(config: Config, now: float) -> None:
    config.last_run_file.write_text(f"{now}\n")


def refresh(run: dict) -> dict:
    return FeedbackService.get_auto_run(run["id"])


def fail(run: dict, error: str) -> str:
    FeedbackService.update_auto_run(run["id"], stage="failed", last_error=error[:4000])
    notify.failure(refresh(run), error)
    return "failed"


def build_failed(config: Config, run: dict, error: str) -> str:
    attempts = run["build_attempts"] + 1
    if attempts >= config.max_build_attempts:
        FeedbackService.update_auto_run(run["id"], build_attempts=attempts)
        return fail(run, f"BUILD failed {attempts} times. Last error:\n{error}")
    FeedbackService.update_auto_run(run["id"], build_attempts=attempts, last_error=error[:4000])
    log.info("build attempt %s failed; will retry next tick: %s", attempts, error[:300])
    return "retry"


def auth_problem(run: dict) -> str:
    FeedbackService.update_auto_run(run["id"], last_error="Claude authentication failed")
    notify.warning("Claude authentication failed (token expired or revoked). "
                   "Create a new one with `claude setup-token`, copy it, then run: runner/setup.sh store-token")
    return "auth"


def git_main(config: Config, *args: str, check: bool = True) -> str:
    return refs.git_main(config, *args, check=check)


def drop_review_branch(config: Config, run: dict) -> None:
    if run.get("change_name"):
        reason = refs.delete_review_branch(config, run["change_name"])
        if reason:
            notify.warning(reason + ". Switch that checkout back to main — never check out a review branch.")


def main_checkout_ready(config: Config) -> str:
    """Return '' if the main checkout is clean and on main, else the reason."""
    if git_main(config, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        return "the main checkout is not on branch main"
    if git_main(config, "status", "--porcelain", "--untracked-files=no"):
        return "the main checkout has uncommitted changes"
    return ""


# ---------- stages ----------


def do_plan(config: Config, session: Session, run: dict, submission: dict) -> str:
    path = Path(run["workspace_path"])
    session.ensure_ready(path)
    ws.clear_output(path)
    prompt = render_prompt(config, "plan.md", BRANCH=run["branch"])
    result = agent.run(config, path, prompt, config.plan, token=session.token,
                       agents_json=session.agents_json)
    log.info("PLAN finished ok=%s cost=$%.2f", result.ok, result.cost_usd)
    if result.auth_failed:
        return auth_problem(run)
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    try:
        out = validate.validate_plan(ws.read_output(path), config, ref)
    except validate.OutputError as e:
        return fail(run, f"PLAN failed: {e}\n\nAgent said: {result.text[-800:]}")
    FeedbackService.update_auto_run(run["id"], stage="planned", change_name=out["change_name"], last_error=None)
    run = refresh(run)
    notify.planned(run, submission, out["summary"])
    return do_build(config, session, run, submission)


def do_build(config: Config, session: Session, run: dict, submission: dict) -> str:
    path = Path(run["workspace_path"])
    FeedbackService.update_auto_run(run["id"], stage="building")
    run = refresh(run)
    drop_review_branch(config, run)  # a new BUILD makes the reviewed commit stale
    session.ensure_ready(path)
    payload = {"submission": submission, "change_name": run["change_name"]}
    if run.get("decision_note"):
        payload["admin_note"] = run["decision_note"]
    ws.write_input(path, payload)
    ws.clear_output(path)
    prompt = render_prompt(config, "build.md", BRANCH=run["branch"], CHANGE_NAME=run["change_name"])
    result = agent.run(config, path, prompt, config.build, token=session.token,
                       agents_json=session.agents_json)
    log.info("BUILD finished ok=%s cost=$%.2f", result.ok, result.cost_usd)
    if result.auth_failed:
        return auth_problem(run)
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    try:
        out = validate.validate_build(ws.read_output(path), config, ref)
    except validate.OutputError as e:
        return build_failed(config, run, f"{e}\n\nAgent said: {result.text[-800:]}")
    verification = verify.run(config, path, session.token)
    if not verification.ok:
        return build_failed(config, run, f"Tests failed in the sandbox: {verification.summary}")
    # Branch before stage: a crash in between resumes as 'building', which drops the branch again.
    reason = refs.set_review_branch(config, run["change_name"], ref)
    if reason:
        notify.warning(reason + ". Switch that checkout back to main — never check out a review branch.")
    FeedbackService.update_auto_run(run["id"], stage="awaiting_decision", build_attempts=0, last_error=None)
    run = refresh(run)
    notify.merge_request(
        run, submission, out["summary"], refs.diffstat(config, ref),
        f"{verification.summary} in the sandbox (no database there — database tests run after ✅, before merging)",
        out["new_dependencies"],
        f"git -C {config.main} diff main...{refs.review_branch(run['change_name']).removeprefix('refs/heads/')}",
        refs.sensitive_paths(refs.changed_paths(config, ref)),
    )
    return "awaiting_decision"


def merge_path(config: Config, session: Session, run: dict, submission: dict) -> str:
    reason = main_checkout_ready(config)
    if reason:
        if run.get("last_error") != reason:
            FeedbackService.update_auto_run(run["id"], last_error=reason)
            notify.warning(f"Merge of {run['change_name']} is waiting: {reason}. Retrying hourly.")
        return "merge_waiting"
    path = Path(run["workspace_path"])
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    # Approved by the admin: run the COMPLETE suite (incl. database tests) on exactly this commit.
    verification = testdb.run_full_suite(config, ref, run["feedback_submission_id"])
    if not verification.ok:
        FeedbackService.update_auto_run(run["id"], decision=None, last_error=verification.summary)
        notify.failure(refresh(run), f"Merge aborted — full test suite failed: {verification.summary}")
        return "merge_aborted"
    name = run["change_name"]
    merged = subprocess.run(
        ["git", *refs.SAFE, "-C", str(config.main), "merge", "--no-ff", "-m",
         f"Merge runner change {name} ({run['branch']})", ref],
        capture_output=True, text=True,
    )
    if merged.returncode != 0:
        git_main(config, "merge", "--abort", check=False)
        FeedbackService.update_auto_run(run["id"], decision=None, last_error=merged.stderr[-2000:])
        notify.failure(refresh(run), f"Merge failed (conflict?):\n{merged.stderr[-1500:]}")
        return "merge_aborted"

    subprocess.run(["openspec", "archive", name, "-y"], cwd=config.main, check=True, capture_output=True)
    git_main(config, "add", "-A", "openspec")
    git_main(config, "commit", "-q", "-m", f"chore: archive {name} and sync specs")
    FeedbackService.resolve_submission(run["feedback_submission_id"])
    subprocess.run([str(config.bot_python), "-m", "pip", "install", "--quiet", "-r",
                    str(config.main / "requirements.txt")], check=True, capture_output=True)
    restart = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.seb.bot"],
                             capture_output=True, text=True)
    ws.remove(config, path)
    refs.delete_ref(config, run["feedback_submission_id"])
    drop_review_branch(config, run)
    FeedbackService.update_auto_run(run["id"], stage="merged", decision=None, last_error=None)
    notify.merged(refresh(run))
    if restart.returncode != 0:
        notify.warning(f"Merged, but restarting the bot failed: {restart.stderr.strip()[:300]}. "
                       "Restart it manually.")
    return "merged"


def reject_path(config: Config, run: dict, submission: dict) -> str:
    FeedbackService.record_event(submission["user_id"], "wont_do", run["feedback_submission_id"])
    path = Path(run["workspace_path"])
    name = run.get("change_name")
    if name and path.exists():
        if git_main(config, "rev-parse", "--abbrev-ref", "HEAD") == "main":
            ref = refs.fetch(config, path, run["feedback_submission_id"])
            rel = f"openspec/changes/archive/{date.today():%Y-%m-%d}-{name}"
            dest = config.main / rel
            if not dest.exists() and refs.has_change(config, ref, name):
                refs.export_change(config, ref, name, dest)
                note = run.get("decision_note") or "(no reason given)"
                (dest / "REJECTED.md").write_text(f"# Rejected\n\nRejected by the admin on {date.today()}.\n\n{note}\n")
                git_main(config, "add", "--", rel)
                git_main(config, "commit", "-q", "-m", f"chore: record rejected change {name}", "--", rel)
        else:
            notify.warning(f"Rejected {name}, but the main checkout is not on main, so the proposal was not archived.")
    ws.remove(config, path)
    refs.delete_ref(config, run["feedback_submission_id"])
    drop_review_branch(config, run)
    FeedbackService.update_auto_run(run["id"], stage="rejected", decision=None)
    notify.rejected(refresh(run))
    return "rejected"


# ---------- tick ----------


def guarded(stage_fn, run: dict, *args) -> str:
    try:
        return stage_fn(*args)
    except IsolationError as e:
        return fail(run, f"Isolation self-test failed — no agent was started.\n{e}")


def handle_inflight(config: Config, session: Session, run: dict) -> str:
    submission = FeedbackService.get_submission(run["feedback_submission_id"])
    stage, decision = run["stage"], run["decision"]
    if stage in ("awaiting_decision", "failed"):
        if decision == "merge" and stage == "awaiting_decision":
            return guarded(merge_path, run, config, session, run, submission)
        if decision == "reject":
            return reject_path(config, run, submission)
        if decision == "changes":
            FeedbackService.update_auto_run(run["id"], decision=None, build_attempts=0, last_error=None)
            run = refresh(run)
            if run["change_name"]:
                return guarded(do_build, run, config, session, run, submission)
            FeedbackService.update_auto_run(run["id"], stage="planning")
            return guarded(do_plan, run, config, session, refresh(run), submission)
        return "waiting"
    if stage == "planning":
        return guarded(do_plan, run, config, session, run, submission)
    if stage in ("planned", "building"):
        return guarded(do_build, run, config, session, run, submission)
    return "noop"


def start_new(config: Config, session: Session, submission: dict, now: float) -> str:
    sub_id = submission["id"]
    path = ws.workspace_path(config, sub_id)
    try:
        run = FeedbackService.create_auto_run(sub_id, ws.branch_name(sub_id), str(path))
    except ClarificationError:
        return "busy"
    mark_last_run(config, now)
    log.info("starting run %s for submission %s", run["id"], sub_id)
    try:
        ws.create(config, sub_id)
    except Exception as e:
        return fail(run, f"Could not create the workspace: {e}")
    ws.write_input(path, {"submission": submission})
    return guarded(do_plan, run, config, session, run, submission)


def tick(config: Config, now: float = None) -> str:
    now = time.time() if now is None else now
    session = Session(config)
    run = FeedbackService.get_inflight_auto_run()
    if run is not None:
        return handle_inflight(config, session, run)
    if not throttle_ok(config, now):
        return "throttled"
    queue = FeedbackService.get_actionable_feedback(user_id=get_admin_user_id())
    if not queue["actionable"]:
        return "idle"
    return start_new(config, session, queue["actionable"][0], now)


def _notify_crash_once(config: Config, error: str) -> None:
    marker = config.runner_home / "last_crash"
    previous = marker.read_text() if marker.exists() else ""
    if previous != error:
        marker.write_text(error)
        try:
            notify.warning(f"tick crashed: {error[:1500]}")
        except Exception:
            log.exception("could not send crash notification")


def main() -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # request URLs contain the bot token
    config = load_config()
    load_main_secrets(config)
    try:
        outcome = tick(config)
    except Exception as e:
        log.exception("tick crashed")
        _notify_crash_once(config, f"{type(e).__name__}: {e}")
        return 1
    (config.runner_home / "last_crash").unlink(missing_ok=True)
    log.info("tick outcome: %s", outcome)
    return 0


if __name__ == "__main__":
    sys.exit(main())
