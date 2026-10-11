"""factory/serve.py: runner runs drawn as dashboard cards (add-software-factory)."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

_spec = importlib.util.spec_from_file_location(
    "factory_serve", Path(__file__).resolve().parent.parent / "factory" / "serve.py")
serve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve)


def _run(**overrides):
    run = {
        "id": uuid4(), "feedback_submission_id": uuid4(), "branch": "auto/1234abcd",
        "change_name": None, "stage": "planning", "decision": None, "decision_note": None,
        "plan_summary": None, "build_attempts": 0, "last_error": None,
        "updated_at": datetime(2026, 10, 11, tzinfo=timezone.utc),
        "bug_text": "calc gives no hint\nsecond line", "suggestion_text": "show an example",
    }
    run.update(overrides)
    return run


def test_every_runner_stage_has_a_column():
    for stage in ("planning", "planned", "building", "awaiting_decision", "merged", "rejected", "failed"):
        assert serve.run_card(_run(stage=stage))["stage"] in {"spec", "build", "needs-human", "merged"}


def test_awaiting_decision_is_waiting_on_telegram():
    card = serve.run_card(_run(stage="awaiting_decision", change_name="add-calc-examples"))
    assert card["stage"] == "needs-human"
    assert "Merge" in card["waiting"]
    assert card["id"] == "add-calc-examples"


def test_card_without_change_name_uses_short_run_id_and_first_line():
    run = _run()
    card = serve.run_card(run)
    assert card["id"] == str(run["id"])[:8]
    assert card["title"] == "calc gives no hint"


def test_files_only_include_what_the_run_has():
    assert set(serve.run_card(_run())["files"]) == {"feedback.md"}
    card = serve.run_card(_run(stage="failed", plan_summary="do x", last_error="boom"))
    assert set(card["files"]) == {"feedback.md", "plan.md", "error.md"}
    assert card["decision"] == "FAILED"


def test_queued_feedback_card():
    sub = {"id": uuid4(), "bug_text": "meal picker repeats", "suggestion_text": "skip recent picks",
           "created_at": datetime(2026, 10, 11, tzinfo=timezone.utc),
           "clarification_question": "Which picks?", "clarification_answer": "the last 3"}
    card = serve.queue_card(sub)
    assert card["stage"] == "queued"
    assert card["feedback_id"] == str(sub["id"])
    assert "the last 3" in card["files"]["feedback.md"]


class _Config:
    def __init__(self, home, throttle_hours=5.0):
        self.logs_dir = home / "logs"
        self.last_run_file = home / "last_run"
        self.throttle_hours = throttle_hours


def test_runner_status_reads_last_tick_and_throttle(tmp_path):
    config = _Config(tmp_path)
    config.logs_dir.mkdir()
    (config.logs_dir / "runner.log").write_text(
        "2026-10-11 03:00:01,100 INFO tick outcome: idle\n"
        "2026-10-11 04:00:02,200 INFO signals: 0 events read\n"
        "2026-10-11 04:00:02,300 INFO tick outcome: throttled\n")
    now = 1_000_000.0
    config.last_run_file.write_text(f"{now - 3600}\n")
    status = serve.runner_status(config, now=now)
    assert status["last_tick"] == "2026-10-11 04:00:02"
    assert status["outcome"] == "throttled"
    assert "5 h" in status["explain"]
    assert status["next_new_run"] is not None


def test_runner_status_without_log(tmp_path):
    status = serve.runner_status(_Config(tmp_path), now=0)
    assert status["last_tick"] is None and "never ticked" in status["explain"]


def test_queued_feedback_from_non_admin_is_flagged():
    sub = {"id": uuid4(), "user_id": 2, "bug_text": "x", "suggestion_text": "y", "created_at": None}
    assert "admin" in serve.queue_card(sub, admin_id=1)["waiting"]
    assert serve.queue_card({**sub, "user_id": 1}, admin_id=1)["waiting"] is None


def test_failed_run_is_open_and_waits_on_the_admin():
    card = serve.run_card(_run(stage="failed", last_error="boom"))
    assert card["stage"] == "needs-human"
    assert "Reject" in card["waiting"]


def test_review_verdicts_become_a_round_of_chips_and_a_file():
    verdicts = {"code": {"verdict": "PASS", "findings": "VERDICT: PASS"},
                "security": {"verdict": "FIXED", "findings": "VERDICT: CHANGES\n- bot.py:9 log leaks token"},
                "ux": {"verdict": "SKIPPED", "findings": ""}, "ui": {"verdict": "SKIPPED", "findings": ""}}
    card = serve.run_card(_run(stage="awaiting_decision", review_verdicts=verdicts))
    assert card["history"] == [{"code": "PASS", "security": "FIXED", "ux": "SKIPPED", "ui": "SKIPPED"}]
    assert "## security: FIXED\nVERDICT: CHANGES\n- bot.py:9 log leaks token" in card["files"]["review.md"]
    assert "ux" not in card["files"]["review.md"]
    assert serve.run_card(_run())["history"] == []
