"""Run the workspace's test suite inside the agent sandbox (design D11).

Tests are agent-authored, so the trusted runner never executes them directly. A small agent run
(Claude Code with Haiku, or Hermes in its Docker sandbox) executes exactly one pytest command; the
verdict comes from the raw tool result in the event stream, never from the model's own description.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from runner import agent, hermes
from runner.config import Config
from runner.selftest import parse_stream

PYTEST_CMD = ".venv/bin/python -m pytest -q tests"
PROMPT = (
    "Run exactly this bash command once, from the current directory, and then reply with only the "
    f"word DONE: {PYTEST_CMD}"
)
HERMES_PROMPT = (
    "Use the terminal tool to run exactly this command once, from the current directory, and then "
    f"reply with only the word DONE: {hermes.PYTEST_CMD}"
)
SUMMARY = re.compile(r"=*\s*(?P<body>(?:\d+ \w+(?:, )?)+) in [\d.]+s", re.MULTILINE)


@dataclass
class Verification:
    ok: bool
    summary: str


def verdict(raw: str, stream=None) -> Verification:
    stream = stream if stream is not None else parse_stream(raw)
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


def run(config: Config, workspace: Path, token) -> Verification:
    prompt = HERMES_PROMPT if config.agent_backend == "hermes" else PROMPT
    stream = agent.probe(config, prompt, "Bash", workspace, token=token, limits=config.selftest,
                         timeout=config.build.timeout_s)
    if not stream.raw:
        return Verification(False, "verification timed out")
    return verdict(stream.raw, stream)
