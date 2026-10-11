"""Serve the factory dashboard on this Mac, with the autonomous runner's runs alongside factory jobs.

    python3 factory/serve.py [port]        # default 8000, bound to 127.0.0.1

Static files come from factory/. GET /runner.json reads the runner's `auto_runs` (read-only) and
returns them as dashboard cards, so the runner shows up on the same board as /factory jobs.
"""

import json
import logging
import sys
from contextlib import closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FACTORY = Path(__file__).resolve().parent
sys.path.insert(0, str(FACTORY.parent))

logger = logging.getLogger(__name__)

RECENT_FINISHED = 10

# auto_runs.stage → the dashboard column it is drawn in
STAGE_COLUMNS = {
    "planning": "spec",
    "planned": "spec",
    "building": "build",
    "awaiting_decision": "needs-human",
    "merged": "merged",
    "rejected": "merged",
    "failed": "merged",
}

RUNS_SQL = """
    SELECT r.id, r.feedback_submission_id, r.branch, r.change_name, r.stage, r.decision,
           r.decision_note, r.plan_summary, r.build_attempts, r.last_error, r.updated_at,
           s.bug_text, s.suggestion_text
    FROM auto_runs r
    JOIN feedback_submissions s ON s.id = r.feedback_submission_id
    WHERE r.stage NOT IN ('merged', 'rejected', 'failed')
       OR r.id IN (SELECT id FROM auto_runs WHERE stage IN ('merged', 'rejected', 'failed')
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
               "awaiting_decision": "waiting for ✅ Merge in Telegram"}.get(run["stage"])
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


def runner_board() -> dict:
    try:
        # Imported here so the board still serves factory jobs under a python without the bot's deps.
        from dotenv import load_dotenv
        from psycopg.rows import dict_row

        from db import get_connection

        load_dotenv(FACTORY.parent / ".env")
        with closing(get_connection()) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(RUNS_SQL, (RECENT_FINISHED,))
            return {"runs": [run_card(r) for r in cur.fetchall()]}
    except ImportError as e:
        return {"runs": [], "error": f"{e.name} is not installed; run serve.py with the bot's python "
                                     "or pip install -r requirements.txt"}
    except Exception as e:  # the board still works without a database
        logger.warning(f"runner.json: {e}")
        return {"runs": [], "error": str(e).splitlines()[0][:200]}


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
