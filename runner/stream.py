"""Backend-neutral views of an agent run: the final result and the raw tool calls/results.

Each backend (runner/agent.py for Claude Code, runner/hermes.py for Hermes Agent) parses its own
output format into these, so the self-test and verification verdicts are shared.
"""

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    ok: bool
    text: str
    cost_usd: float
    auth_failed: bool
    raw: str


@dataclass
class StreamSummary:
    calls: list = field(default_factory=list)       # (tool name, target) per tool_use
    results: list = field(default_factory=list)     # (is_error, text) per tool_result
    unsandboxed: bool = False
    raw: str = ""
