"""Verdict tests for the sandboxed verification run (design D11): only raw tool output counts."""

import json

from runner.verify import verdict


def _stream(cmd, output, error=False, final="DONE", unsandboxed=False):
    inp = {"command": cmd}
    if unsandboxed:
        inp["dangerouslyDisableSandbox"] = True
    events = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": inp}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": error, "content": output}]}},
        {"type": "result", "result": final},
    ]
    return "\n".join(json.dumps(e) for e in events)


CMD = ".venv/bin/python -m pytest -q tests"


def test_pass():
    v = verdict(_stream(CMD, "........\n85 passed in 1.04s\n"))
    assert v.ok and v.summary == "85 passed"


def test_failures():
    v = verdict(_stream(CMD, "..F\n1 failed, 84 passed in 1.2s\n", error=True))
    assert not v.ok and "1 failed" in v.summary


def test_errors_without_exit_flag_still_fail():
    assert not verdict(_stream(CMD, "E\n2 errors, 10 passed in 0.5s\n")).ok


def test_no_summary_line():
    assert not verdict(_stream(CMD, "ModuleNotFoundError: No module named pytest")).ok


def test_no_tool_call():
    raw = json.dumps({"type": "result", "result": "All 85 tests passed!"})
    assert not verdict(raw).ok


def test_model_lies_about_result():
    v = verdict(_stream(CMD, "1 failed, 84 passed in 1.2s", error=True, final="All tests passed, DONE"))
    assert not v.ok


def test_unsandboxed_attempt_fails():
    assert not verdict(_stream(CMD, "85 passed in 1.0s", unsandboxed=True)).ok


def test_skipped_counts_are_fine():
    v = verdict(_stream(CMD, "85 passed, 3 skipped in 1.0s"))
    assert v.ok
