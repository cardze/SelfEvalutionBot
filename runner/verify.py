"""Run the workspace's test suite inside the Claude sandbox (design D11).

Tests are agent-authored, so the trusted runner never executes them directly. A small Haiku run
executes exactly one pytest command under the runner settings; the verdict comes from the raw
tool result in the stream-json events, never from the model's own description.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from runner import agent
from runner.config import Config
from runner.selftest import parse_stream

PYTEST_CMD = ".venv/bin/python -m pytest -q tests"
PROMPT = (
    "Run exactly this bash command once, from the current directory, and then reply with only the "
    f"word DONE: {PYTEST_CMD}"
)
SUMMARY = re.compile(r"=*\s*(?P<body>(?:\d+ \w+(?:, )?)+) in [\d.]+s", re.MULTILINE)


@dataclass
class Verification:
    ok: bool
    summary: str


def verdict(raw: str) -> Verification:
    stream = parse_stream(raw)
    pytest_calls = [i for i, (_, target) in enumerate(stream.calls) if "pytest" in target]
    if not pytest_calls:
        return Verification(False, "the verification run made no pytest call")
    if stream.unsandboxed:
        return Verification(False, "the verification run tried to leave the sandbox")
    if not stream.results:
        return Verification(False, "no tool result for the pytest call")
    is_error, text = stream.results[-1]
    matches = list(SUMMARY.finditer(text))
    if not matches:
        return Verification(False, "no pytest summary line in the output: " + text.strip()[-300:])
    body = matches[-1].group("body")
    failed = re.search(r"\b\d+ (failed|errors?)\b", body)
    passed = re.search(r"\b(\d+) passed\b", body)
    if is_error or failed or not passed:
        return Verification(False, body)
    return Verification(True, body)


def run(config: Config, workspace: Path, token: str) -> Verification:
    cmd = agent.claude_command(config, PROMPT, config.selftest, model=config.selftest_model,
                               allowed_tools=["Bash"], stream=True)
    try:
        proc = subprocess.run(cmd, cwd=workspace, env=agent.build_env(config, workspace, token),
                              capture_output=True, text=True, timeout=config.build.timeout_s)
    except subprocess.TimeoutExpired:
        return Verification(False, "verification timed out")
    return verdict(proc.stdout + proc.stderr)
