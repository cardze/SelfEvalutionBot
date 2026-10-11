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
