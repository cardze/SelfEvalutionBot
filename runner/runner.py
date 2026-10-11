"""One tick of the autonomous feedback runner (design D4). Started hourly by runner/run.sh.

    decisions → resume in-flight run → throttle → pick admin feedback → PLAN → 📋 → BUILD → verify → 🔀

Everything with side effects outside the workspace (Telegram, merge, archive, resolve, bot restart)
happens here, in the trusted process. Agents only ever run sandboxed (runner/agent.py) after a
passing isolation self-test (runner/selftest.py).
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

from psycopg.types.json import Jsonb

from clarify import get_admin_user_id
from runner import agent, guard, hermes, notify, refs, review, selftest, signals, snapshot, templates, testdb, validate, verify
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
            if self.config.agent_backend == "hermes":
                self.token, self.agents_json = None, None
                hermes.ensure_profile(self.config)
                snapshot.export_hermes_skills(self.config)
            else:
                # Re-rendered every tick, like the Hermes profile: a pulled template change (e.g. the
                # ~/.hermes deny of guard-hermes-from-runner) must apply without a manual setup step.
                templates.render_settings(self.config)
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


def backend_values(config: Config) -> dict:
    """Commands the prompts use for Python, per backend (add-hermes-agent-backend, design H6)."""
    if config.agent_backend == "hermes":
        return {"VENV_SETUP": hermes.VENV_SETUP, "PYTHON": f"{hermes.VENV}/bin/python",
                "PIP": f"{hermes.VENV}/bin/pip"}
    return {"PYTHON": ".venv/bin/python", "PIP": ".venv/bin/pip"}


def render_prompt(config: Config, name: str, **values) -> str:
    prompts = config.main / "runner/prompts"
    text = (prompts / name).read_text()
    if config.agent_backend == "hermes":
        text += (prompts / "hermes.md").read_text()
    for key, value in {**backend_values(config), "PROTECTED": guard.prompt_rule(config), **values}.items():
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


def auth_problem(config: Config, run: dict) -> str:
    if config.agent_backend == "hermes":
        FeedbackService.update_auto_run(run["id"], last_error="Hermes provider authentication failed")
        notify.warning("Hermes provider authentication failed (API key or login expired). Re-authenticate "
                       f"the runner profile: HERMES_HOME={config.hermes_home} hermes auth add <provider> "
                       f"(or update the key in {config.hermes_env_file}), then run: runner/setup.sh selftest")
        return "auth"
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
    log.info("PLAN finished ok=%s cost=$%.2f backend=%s", result.ok, result.cost_usd, config.agent_backend)
    if result.auth_failed:
        return auth_problem(config, run)
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    try:
        out = validate.validate_plan(ws.read_output(path), config, ref)
    except validate.OutputError as e:
        return fail(run, f"PLAN failed: {e}\n\nAgent said: {result.text[-800:]}")
    blocked = guard.violations(config, ref)
    if blocked:
        return fail(run, f"PLAN refused: {guard.describe(blocked)}")
    plan = json.dumps({"summary": out["summary"], "impact": out["impact"]})
    FeedbackService.update_auto_run(run["id"], stage="planned", change_name=out["change_name"],
                                    plan_summary=plan, plan_message_id=None, last_error=None)
    run = refresh(run)
    if FeedbackService.is_signal_submission(run["feedback_submission_id"]):
        return send_held_plan(run, submission)
    notify.planned(run, submission, out["summary"], out["impact"])
    return do_build(config, session, run, submission)


def send_held_plan(run: dict, submission: dict) -> str:
    """Runner-suggested work waits after PLAN for ▶️ Build / ❌ Drop (design D12)."""
    plan = json.loads(run["plan_summary"])
    message_id = notify.planned(run, submission, plan["summary"], plan["impact"], gated=True)
    FeedbackService.update_auto_run(run["id"], plan_message_id=message_id)
    return "waiting"


def do_build(config: Config, session: Session, run: dict, submission: dict) -> str:
    path = Path(run["workspace_path"])
    FeedbackService.update_auto_run(run["id"], stage="building", review_verdicts=None)
    run = refresh(run)
    drop_review_branch(config, run)  # a new BUILD makes the reviewed commit stale
    session.ensure_ready(path)
    payload = {"submission": submission, "change_name": run["change_name"]}
    if run.get("decision_note"):
        payload["admin_note"] = run["decision_note"]
    # No decision outlives the BUILD it led to (e.g. ▶️ Build), so none can leak into the 🔀 stage.
    # The note stays: build retries keep using the admin's 💬 instructions.
    FeedbackService.update_auto_run(run["id"], decision=None)
    ws.write_input(path, payload)
    ws.clear_output(path)
    prompt = render_prompt(config, "build.md", BRANCH=run["branch"], CHANGE_NAME=run["change_name"])
    result = agent.run(config, path, prompt, config.build, token=session.token,
                       agents_json=session.agents_json)
    log.info("BUILD finished ok=%s cost=$%.2f backend=%s", result.ok, result.cost_usd, config.agent_backend)
    if result.auth_failed:
        return auth_problem(config, run)
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    blocked = guard.violations(config, ref)
    if blocked:  # not retried: another attempt at the same plan would need the same paths
        return fail(run, f"BUILD refused: {guard.describe(blocked)}")
    try:
        out = validate.validate_build(ws.read_output(path), config, ref)
    except validate.OutputError as e:
        return build_failed(config, run, f"{e}\n\nAgent said: {result.text[-800:]}")
    verification = verify.run(config, path, session.token)
    if not verification.ok:
        return build_failed(config, run, f"Tests failed in the sandbox: {verification.summary}")
    outcome, ref, verdicts, verification = do_review(config, session, run, path, ref, verification)
    if outcome:
        return outcome
    out["new_dependencies"] = refs.added_requirements(config, ref)  # the fix round may have added some
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
        review.summary_line(verdicts),
    )
    return "awaiting_decision"


def do_review(config: Config, session: Session, run: dict, path: Path, ref: str, verification):
    """REVIEW (add-runner-review-step): reviewers on the diff, one fix round, tests again if it changed.

    Returns (outcome, ref, verdicts, verification); outcome is "" to go on to the merge request.
    """
    reviewers = review.reviewers_for([text for _, text in refs.added_lines(config, ref)])
    review.clear(path)
    prompt = render_prompt(config, "review.md", BRANCH=run["branch"], CHANGE_NAME=run["change_name"],
                           REVIEWERS=review.agent_names(reviewers))
    result = agent.run(config, path, prompt, config.build, token=session.token,
                       agents_json=session.agents_json)
    log.info("REVIEW finished ok=%s cost=$%.2f reviewers=%s", result.ok, result.cost_usd, ",".join(reviewers))
    if result.auth_failed:
        return auth_problem(config, run), ref, {}, verification
    built = refs.head(config, ref)
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    fixed = refs.head(config, ref) != built
    verdicts = review.read_verdicts(path, reviewers, fixed)
    FeedbackService.update_auto_run(run["id"], review_verdicts=Jsonb(verdicts))
    if fixed:
        blocked = guard.violations(config, ref)
        if blocked:
            return fail(run, f"REVIEW fix refused: {guard.describe(blocked)}"), ref, verdicts, verification
        verification = verify.run(config, path, session.token)
        if not verification.ok:
            return (build_failed(config, run, f"Tests failed after the review fixes: {verification.summary}"),
                    ref, verdicts, verification)
    return "", ref, verdicts, verification


def merge_path(config: Config, session: Session, run: dict, submission: dict) -> str:
    reason = main_checkout_ready(config)
    if reason:
        if run.get("last_error") != reason:
            FeedbackService.update_auto_run(run["id"], last_error=reason)
            notify.warning(f"Merge of {run['change_name']} is waiting: {reason}. Retrying hourly.")
        return "merge_waiting"
    path = Path(run["workspace_path"])
    ref = refs.fetch(config, path, run["feedback_submission_id"])
    # Re-checked on exactly this commit: the workspace is agent-controlled (guard-hermes-from-runner G3).
    blocked = guard.violations(config, ref)
    if blocked:
        FeedbackService.update_auto_run(run["id"], decision=None, last_error=guard.describe(blocked)[:4000])
        notify.failure(refresh(run), f"Merge refused. {guard.describe(blocked)}")
        return "merge_aborted"
    # Approved by the admin: run the COMPLETE suite (incl. database tests) on main merged with this commit.
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

    archived = subprocess.run(["openspec", "archive", name, "-y"], cwd=config.main, capture_output=True, text=True)
    if (config.main / "openspec/changes" / name).exists():
        # openspec exits 0 when it refuses (e.g. an invalid spec). The code is merged; only the archive is left.
        notify.warning(f"Merged {name}, but openspec did not archive it:\n"
                       f"{(archived.stdout + archived.stderr).strip()[-1200:]}\n"
                       f"Fix that, then run: openspec archive {name} -y")
    else:
        git_main(config, "add", "-A", "openspec")
        git_main(config, "commit", "-q", "-m", f"chore: archive {name} and sync specs")
    FeedbackService.resolve_submission(run["feedback_submission_id"])
    install_requirements(config)
    restart = None
    if config.bot_service == "launchd":
        restart = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/com.seb.bot"],
                                 capture_output=True, text=True)
    ws.remove(config, path)
    refs.delete_ref(config, run["feedback_submission_id"])
    drop_review_branch(config, run)
    FeedbackService.update_auto_run(run["id"], stage="merged", decision=None, last_error=None)
    notify.merged(refresh(run))
    if config.bot_service == "hermes":
        # This tick runs inside the gateway's cron scheduler: restart it only now, detached, so the
        # restart cannot cut off this run before it is recorded as merged (design B5).
        restart = restart_hermes_gateway(config)
    if restart.returncode != 0:
        notify.warning(f"Merged, but restarting the bot failed: {restart.stderr.strip()[:300]}. "
                       "Restart it manually.")
    return "merged"


def install_requirements(config: Config) -> None:
    """Into the runner's own Python only. In Hermes mode a runner-built change cannot change
    requirements.txt or the plugin (guard-hermes-from-runner G4), so Hermes's environment is never
    touched here; a person who changes them runs `hermes_profile/setup.sh sync`."""
    subprocess.run([str(config.bot_python), "-m", "pip", "install", "--quiet", "-r",
                    str(config.main / "requirements.txt")], check=True, capture_output=True)


def restart_hermes_gateway(config: Config) -> subprocess.CompletedProcess:
    """Restart the `seb` profile's standalone gateway (hermes_profile/setup.sh sets
    gateway.standalone) in its own session, so it outlives this tick."""
    cmd = ["sh", "-c", 'sleep 5; exec "$0" "$@"', config.hermes_bin, "-p", config.hermes_profile,
           "gateway", "restart"]
    try:
        subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))
    return subprocess.CompletedProcess(cmd, 0, "", "")


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
    if stage == "planned" and FeedbackService.is_signal_submission(run["feedback_submission_id"]):
        if decision == "reject":
            return reject_path(config, run, submission)
        if decision == "build":
            return guarded(do_build, run, config, session, run, submission)
        if run.get("plan_message_id") is None and run.get("plan_summary"):
            return send_held_plan(run, submission)  # the 📋 was lost: ask again
        return "waiting"
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


def scan_signals(config: Config, now: float) -> None:
    """Runner signals first in every tick; a failure here never blocks the rest (design D7)."""
    try:
        stats = signals.scan(config, datetime.fromtimestamp(now, timezone.utc))
        log.info("signals: %(read)d events read, %(dropped)d dropped, %(suggested)d suggested, "
                 "%(reset)d reset, %(dismissed)d dismissed", stats)
    except Exception:
        log.exception("signals: scan failed")


def tick(config: Config, now: float = None) -> str:
    now = time.time() if now is None else now
    scan_signals(config, now)
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
