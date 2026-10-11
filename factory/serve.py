"""Serve the factory dashboard on this Mac, with the autonomous runner's runs alongside factory jobs.

    python3 factory/serve.py [port]        # default 8000, bound to 127.0.0.1

Static files come from factory/. GET /runner.json reads the runner's `auto_runs` (read-only) and
returns them as dashboard cards, plus the feedback still waiting to be picked up (the same queue as
`ask.py next`), so the runner and the /feedback queue show up on the same board as /factory jobs.
"""

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FACTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(FACTORY.parent))

logger = logging.getLogger(__name__)

RECENT_FINISHED = 10
LOG_TAIL_BYTES = 64_000

# What the runner's last tick outcome means, for the status line
OUTCOMES = {
    "idle": "nothing to do: no actionable feedback from the admin",
    "throttled": "no new run yet: the runner starts at most one new run every {throttle} h",
    "busy": "another run was being created",
    "waiting": "waiting for you in Telegram",
    "noop": "nothing to do for the run in flight",
}
TICK_LINE = re.compile(r"^(\S+ \S+?)(?:,\d+)? \w+ (tick outcome: (\S+)|tick crashed)")

# auto_runs.stage → the dashboard column it is drawn in
STAGE_COLUMNS = {
    "planning": "spec",
    "planned": "spec",
    "building": "build",
    "awaiting_decision": "needs-human",
    "merged": "merged",
    "rejected": "merged",
    "failed": "needs-human",  # still open: it blocks new runs until you reject or retry it
}

# auto_runs.decision → the Telegram button that set it
QUEUED_DECISIONS = {"merge": "✅ Merge", "reject": "❌ Reject", "changes": "💬 Request changes", "build": "▶️ Build"}

RUNS_SQL = """
    SELECT r.id, r.feedback_submission_id, r.branch, r.change_name, r.stage, r.decision,
           r.decision_note, r.plan_summary, r.build_attempts, r.last_error, r.updated_at,
           s.bug_text, s.suggestion_text
    FROM auto_runs r
    JOIN feedback_submissions s ON s.id = r.feedback_submission_id
    WHERE r.stage NOT IN ('merged', 'rejected')
       OR r.id IN (SELECT id FROM auto_runs WHERE stage IN ('merged', 'rejected')
                   ORDER BY updated_at DESC LIMIT %s)
    ORDER BY r.updated_at DESC
"""


def run_card(run: dict) -> dict:
    """One auto_runs row as a dashboard card; `files` are shown when the card is opened."""
    files = {"feedback.md": f"# Feedback\n## What didn't meet expectations\n{run['bug_text']}\n"
                            f"## Suggested fix\n{run['suggestion_text']}\n"}
    if run.get("plan_summary"):
        files["plan.md"] = f"# Plan\n{run['plan_summary']}\n"
    if run.get("last_error"):
        files["error.md"] = f"# Last error\n```\n{run['last_error']}\n```\n"
    if run.get("decision_note"):
        files["note.md"] = f"# Your note\n{run['decision_note']}\n"
    waiting = {"planned": "waiting for ▶️ Build in Telegram",
               "awaiting_decision": "waiting for ✅ Merge in Telegram",
               "failed": "failed: ❌ Reject or 💬 Request changes in Telegram; no new run starts until then"}.get(run["stage"])
    if run.get("decision") and run["stage"] not in ("merged", "rejected"):
        # Your tap only queues the decision; the runner acts on it at its next tick.
        tapped = QUEUED_DECISIONS.get(run["decision"], run["decision"])
        waiting = f"{tapped} queued: the runner acts on it at its next tick (or press the seb-runner cron)"
    return {
        "id": run["change_name"] or str(run["id"])[:8],
        "title": run["bug_text"].splitlines()[0][:80] if run["bug_text"] else "(no text)",
        "branch": run["branch"],
        "stage": STAGE_COLUMNS.get(run["stage"], "spec"),
        "runner_stage": run["stage"],
        "waiting": waiting,
        "decision": {"merged": "MERGED", "rejected": "REJECTED", "failed": "FAILED"}.get(run["stage"]),
        "build_attempts": run["build_attempts"],
        "feedback_id": str(run["feedback_submission_id"]),
        "updated": run["updated_at"].isoformat() if run.get("updated_at") else None,
        "files": files,
    }


def tail(path: Path) -> list[str]:
    with path.open("rb") as f:
        f.seek(max(0, path.stat().st_size - LOG_TAIL_BYTES))
        return f.read().decode(errors="replace").splitlines()


def runner_status(config, now: float = None) -> dict:
    """The runner's last tick (from its own log) and when it may start a new run."""
    now = time.time() if now is None else now
    status = {"last_tick": None, "outcome": None, "explain": None, "next_new_run": None}
    try:
        lines = tail(config.logs_dir / "runner.log")
    except OSError:
        status["explain"] = f"no runner log yet at {config.logs_dir / 'runner.log'}: the runner has never ticked here"
        return status
    for line in reversed(lines):
        m = TICK_LINE.match(line)
        if m:
            status["last_tick"] = m.group(1)
            status["outcome"] = m.group(3) or "crashed"
            break
    try:
        last = float(config.last_run_file.read_text().strip())
        if now - last < config.throttle_hours * 3600:
            status["next_new_run"] = datetime.fromtimestamp(last + config.throttle_hours * 3600).isoformat(timespec="minutes")
    except (OSError, ValueError):
        pass
    outcome = status["outcome"]
    if outcome == "crashed":
        status["explain"] = f"the last tick crashed; see {config.logs_dir / 'runner.log'}"
    elif outcome:
        status["explain"] = OUTCOMES.get(outcome, outcome).format(throttle=f"{config.throttle_hours:g}")
    return status


def queue_card(sub: dict, admin_id: int = None) -> dict:
    """One actionable feedback submission (not yet picked up) as a card in the Queued column."""
    text = f"# Feedback\n## What didn't meet expectations\n{sub['bug_text']}\n## Suggested fix\n{sub['suggestion_text']}\n"
    if sub.get("clarification_answer"):
        text += f"## Clarification\n{sub.get('clarification_question') or ''}\n\n{sub['clarification_answer']}\n"
    return {
        "id": str(sub["id"])[:8],
        "title": sub["bug_text"].splitlines()[0][:80] if sub["bug_text"] else "(no text)",
        "branch": "",
        "stage": "queued",
        "waiting": ("the runner only builds the admin's feedback; use /factory feedback"
                    if admin_id is not None and sub.get("user_id") != admin_id else None),
        "decision": None,
        "feedback_id": str(sub["id"]),
        "updated": sub["created_at"].isoformat() if sub.get("created_at") else None,
        "files": {"feedback.md": text},
    }


def _load_env():
    """Use the database the runner uses: the .env of the checkout in ~/.seb-runner/config.env (MAIN)."""
    try:
        from runner.config import load_config, load_main_secrets
        config = load_config()
        load_main_secrets(config)
        return config
    except Exception as e:  # no runner set up on this machine: fall back to this checkout's .env
        logger.info(f"runner config unavailable: {e}")
        from dotenv import load_dotenv
        load_dotenv(FACTORY.parent / ".env")
        return None


def runner_board() -> dict:
    status = None
    try:
        config = _load_env()
        status = runner_status(config) if config else None
        # Imported here so the board still serves factory jobs under a python without the bot's deps.
        from psycopg.rows import dict_row

        from db import get_connection
        from storage import FeedbackService

        admin = os.environ.get("ADMIN_USER_ID")
        admin_id = int(admin) if admin and admin.isdigit() else None
        with closing(get_connection()) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(RUNS_SQL, (RECENT_FINISHED,))
            runs = [run_card(r) for r in cur.fetchall()]
        queue = [queue_card(s, admin_id) for s in FeedbackService.get_actionable_feedback()["actionable"]]
        return {"runs": runs + queue, "status": status}
    except ImportError as e:
        return {"runs": [], "status": status, "error": f"{e.name} is not installed; run serve.py with "
                                                       "the bot's python or pip install -r requirements.txt"}
    except Exception as e:  # the board still works without a database
        logger.warning(f"runner.json: {e}")
        return {"runs": [], "status": status, "error": str(e).splitlines()[0][:200]}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/runner.json":
            return super().do_GET()
        body = json.dumps(runner_board(), default=str, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=str(FACTORY)))
    print(f"Factory dashboard: http://localhost:{port}/dashboard.html")
    server.serve_forever()


if __name__ == "__main__":
    main()
