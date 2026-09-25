"""Start a sandboxed headless Claude Code run inside a workspace (design D5).

The agent gets a freshly built environment: no production secrets and no database credentials
(design D10: the sandbox has no database; DB tests skip there and run after the admin approves).
The OAuth token is passed to the `claude` process, which does not expose it to the agent's shell
(verified during exploration).
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from runner.config import Config, StageLimits

AUTH_FAILURE_MARKERS = ("Failed to authenticate", "OAuth session expired", "Invalid API key")


@dataclass
class AgentResult:
    ok: bool
    text: str
    cost_usd: float
    auth_failed: bool
    raw: str


def build_env(config: Config, workspace: Path, token: str) -> dict:
    home = Path.home()
    env = {
        "PATH": ":".join([
            str(workspace / ".venv/bin"), str(home / ".local/bin"), "/opt/homebrew/bin",
            "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
        ]),
        "HOME": str(home),
        "LANG": "en_US.UTF-8",
        "VIRTUAL_ENV": str(workspace / ".venv"),
        "PIP_CACHE_DIR": str(workspace / ".auto/pip-cache"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_AUTHOR_NAME": "seb-runner",
        "GIT_AUTHOR_EMAIL": "runner@localhost",
        "GIT_COMMITTER_NAME": "seb-runner",
        "GIT_COMMITTER_EMAIL": "runner@localhost",
        "CLAUDE_CODE_OAUTH_TOKEN": token,
    }
    return env


def claude_command(config: Config, prompt: str, limits: StageLimits, *,
                   agents_json: Optional[str] = None, agent: Optional[str] = None,
                   model: Optional[str] = None, allowed_tools: Optional[list] = None,
                   stream: bool = False) -> list:
    cmd = [
        "perl", "-e", "alarm shift; exec @ARGV", str(limits.timeout_s),
        "claude", "-p", prompt,
        "--setting-sources", "user",
        "--settings", str(config.settings_file),
        "--max-turns", str(limits.max_turns),
        "--max-budget-usd", str(limits.budget_usd),
    ]
    if agents_json:
        cmd += ["--agents", agents_json]
    if agent:
        cmd += ["--agent", agent]
    if config.snapshot_home.exists():
        cmd += ["--add-dir", str(config.snapshot_home)]
    if model:
        cmd += ["--model", model]
    if allowed_tools:
        cmd += ["--allowedTools", *allowed_tools]
    cmd += ["--output-format", "stream-json", "--verbose"] if stream else ["--output-format", "json"]
    return cmd


def parse_result(raw: str) -> AgentResult:
    auth_failed = any(marker in raw for marker in AUTH_FAILURE_MARKERS)
    try:
        data = json.loads(raw[raw.index("{"):])
    except ValueError:
        return AgentResult(False, raw[-2000:], 0.0, auth_failed, raw)
    text = data.get("result") or ""
    ok = data.get("type") == "result" and not data.get("is_error")
    return AgentResult(ok and not auth_failed, text, float(data.get("total_cost_usd") or 0), auth_failed, raw)


def run(config: Config, workspace: Path, prompt: str, limits: StageLimits, *,
        token: str, agents_json: str) -> AgentResult:
    cmd = claude_command(config, prompt, limits, agents_json=agents_json, agent="openspec-leader")
    try:
        proc = subprocess.run(cmd, cwd=workspace, env=build_env(config, workspace, token),
                              capture_output=True, text=True, timeout=limits.timeout_s + 60)
    except subprocess.TimeoutExpired:
        return AgentResult(False, "Agent run timed out", 0.0, False, "")
    raw = proc.stdout + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode == 142:  # SIGALRM from the perl timeout wrapper
        return AgentResult(False, f"Agent run exceeded {limits.timeout_s}s", 0.0, False, raw)
    return parse_result(proc.stdout or raw)
