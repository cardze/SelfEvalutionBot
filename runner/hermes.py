"""Hermes Agent backend (design H2–H8 of add-hermes-agent-backend).

Runs `hermes chat --query-file - --format stream-json` under the runner's own Hermes profile
(HERMES_HOME, default ~/.hermes/profiles/seb-runner). Tool calls execute in a fresh Docker container
that sees only the workspace (runner/hermes/config.template.json); provider credentials stay in the
profile on the host. Everything Hermes-specific — command line, environment, profile rendering and
its pre-flight check, JSONL parsing — lives here.
"""

import json
import subprocess
from pathlib import Path
from typing import Optional

from runner.config import Config, StageLimits, parse_env_file
from runner.stream import AgentResult, StreamSummary

TEMPLATE = Path(__file__).resolve().parent / "hermes" / "config.template.json"
SANDBOX_IMAGE = "seb-runner-sandbox:latest"
SANDBOX_NETWORK = "seb-runner-sandbox"
EGRESS_HOST = "seb-runner-egress"

STAGE_TOOLSETS = ("terminal", "file", "todo", "delegation")
PROBE_TOOLSETS = {"Bash": "terminal", "Read": "file"}   # runner tool kind → Hermes toolset
TOOL_NAMES = {"Bash": "terminal", "Read": "read_file"}  # runner tool kind → Hermes tool name
SKILLS_CATEGORY = "seb-runner"                          # $HERMES_HOME/skills/seb-runner/<skill>/
LEADER_SKILL = "seb-agent-openspec-leader"

AUTH_FAILURE_MARKERS = ("401", "Unauthorized", "AuthenticationError", "invalid_api_key",
                        "Invalid API key", "No API key", "No inference provider",
                        "credentials or agent init failed", "not connected to any AI provider")

# Container-local venv (the host's macOS .venv cannot run in the Linux sandbox; design H6).
VENV = "/tmp/seb-venv"
VENV_SETUP = f"python3 -m venv {VENV} && {VENV}/bin/pip install -q -r requirements.txt pytest"
PYTEST_CMD = f"set -o pipefail; {VENV_SETUP} && {VENV}/bin/python -m pytest -q tests 2>&1 | tail -n 40"


# ---------- profile ----------


def render_profile(config: Config) -> Path:
    """Write the runner profile's config.yaml from the template (JSON is valid YAML)."""
    text = TEMPLATE.read_text()
    for key, value in {"SANDBOX_IMAGE": SANDBOX_IMAGE, "SANDBOX_NETWORK": SANDBOX_NETWORK,
                       "EGRESS_HOST": EGRESS_HOST}.items():
        text = text.replace("{{" + key + "}}", value)
    if "{{" in text:
        raise ValueError("Unrendered placeholder left in the Hermes profile template")
    data = json.loads(text)
    config.hermes_home.mkdir(parents=True, exist_ok=True)
    config.hermes_config_file.write_text(json.dumps(data, indent=2) + "\n")
    return config.hermes_config_file


def profile_problems(config: Config) -> list[str]:
    """Reasons the rendered profile would not isolate tool calls; empty when it is safe (H5, H7)."""
    try:
        data = json.loads(config.hermes_config_file.read_text())
    except (OSError, ValueError) as e:
        return [f"cannot read {config.hermes_config_file}: {e}"]
    term = data.get("terminal") or {}
    problems = []
    if term.get("backend") != "docker":
        problems.append(f"terminal.backend is {term.get('backend')!r}, not 'docker'")
    if term.get("docker_mount_cwd_to_workspace") is not True:
        problems.append("the workspace is not mounted into the container")
    for key in ("docker_volumes", "docker_forward_env", "env_passthrough"):
        if term.get(key):
            problems.append(f"terminal.{key} is not empty")
    if term.get("container_persistent") is not False or term.get("docker_persist_across_processes") is not False:
        problems.append("the sandbox container is reused across runs")
    if f"--network={SANDBOX_NETWORK}" not in (term.get("docker_extra_args") or []):
        problems.append(f"the container is not attached to the {SANDBOX_NETWORK} network")
    if (data.get("memory") or {}).get("memory_enabled") is not False:
        problems.append("persistent memory is enabled")
    if (data.get("skills") or {}).get("project_discovery") is not False:
        problems.append("project skills discovery is enabled")
    return problems


def ensure_profile(config: Config) -> None:
    render_profile(config)
    problems = profile_problems(config)
    if problems:
        raise RuntimeError("Hermes profile is not isolated: " + "; ".join(problems))


def secret_markers(config: Config) -> tuple:
    """Leak markers: the first 12 characters of every non-trivial value in the profile .env."""
    values = parse_env_file(config.hermes_env_file).values()
    return tuple(v[:12] for v in values if len(v) >= 16)


def exported_skills(config: Config) -> list[str]:
    """Names of the skills snapshotted from main (runner/snapshot.py), leader first."""
    root = config.hermes_home / "skills" / SKILLS_CATEGORY
    names = sorted(p.parent.name for p in root.glob("*/SKILL.md")) if root.exists() else []
    if LEADER_SKILL not in names:
        raise RuntimeError(f"No {LEADER_SKILL} skill in {root}; the main snapshot was not exported")
    return [LEADER_SKILL] + [n for n in names if n != LEADER_SKILL]


# ---------- command ----------


def build_env(config: Config) -> dict:
    home = Path.home()
    return {
        "PATH": ":".join([
            str(home / ".local/bin"), str(home / ".hermes/bin"), "/opt/homebrew/bin",
            "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin",
        ]),
        "HOME": str(home),
        "LANG": "en_US.UTF-8",
        "HERMES_HOME": str(config.hermes_home),
        "HERMES_IGNORE_RULES": "1",
    }


def command(config: Config, limits: StageLimits, toolsets, *, skills=(),
            model: Optional[str] = None) -> list:
    cmd = [
        "perl", "-e", "alarm shift; exec @ARGV", str(limits.timeout_s),
        config.hermes_bin, "chat", "--query-file", "-", "--format", "stream-json",
        "--source", "tool", "--ignore-rules", "--yolo",
        "--max-turns", str(limits.max_turns), "--run-budget", str(limits.timeout_s),
        "-t", ",".join(toolsets),
    ]
    if skills:
        cmd += ["-s", ",".join(skills)]
    model = model or config.hermes_model
    if model:
        cmd += ["-m", model]
    if config.hermes_provider:
        cmd += ["--provider", config.hermes_provider]
    return cmd


def execute(cmd: list, prompt: str, cwd: Path, env: dict, timeout: int) -> tuple[int, str]:
    """Run Hermes with the prompt on stdin. Returns (returncode, stdout + stderr)."""
    try:
        proc = subprocess.run(cmd, input=prompt, cwd=cwd, env=env, capture_output=True, text=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return -1, ""
    return proc.returncode, proc.stdout + ("\n" + proc.stderr if proc.stderr else "")


# ---------- parsing ----------


def _events(raw: str):
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def tool_output(text: str) -> tuple[str, Optional[int]]:
    """Unwrap the terminal tool's JSON result ({"output", "exit_code", "error"}) into plain text."""
    try:
        data = json.loads(text)
    except ValueError:
        return text, None
    if not isinstance(data, dict) or "output" not in data:
        return text, None
    out = str(data.get("output") or "")
    if data.get("error"):
        out += "\n" + str(data["error"])
    code = data.get("exit_code")
    return out, code if isinstance(code, int) else None


def parse_stream(raw: str) -> StreamSummary:
    summary = StreamSummary(raw=raw)
    for event in _events(raw):
        if event.get("type") == "tool_use":
            inp = event.get("input") or {}
            target = inp.get("command") or inp.get("path") or inp.get("file_path") or inp.get("pattern")
            summary.calls.append((event.get("name"), str(target)))
        elif event.get("type") == "tool_result":
            text, code = tool_output(str(event.get("output") or ""))
            is_error = bool(event.get("is_error")) or (code is not None and code != 0)
            summary.results.append((is_error, text))
    return summary


def parse_result(raw: str) -> AgentResult:
    final = None
    for event in _events(raw):
        if event.get("type") == "result":
            final = event
    # Diagnostics go to stderr (the non-JSON lines); tool output inside events is agent-controlled.
    diagnostics = "\n".join(line for line in raw.splitlines() if not line.lstrip().startswith("{"))
    if final is None:
        return AgentResult(False, raw[-2000:], 0.0, any(m in diagnostics for m in AUTH_FAILURE_MARKERS), raw)
    error = str(final.get("error") or "")
    auth_failed = bool(error) and any(m in error + "\n" + diagnostics for m in AUTH_FAILURE_MARKERS)
    ok = final.get("exit_code") == 0 and not error
    text = final.get("text") or error
    return AgentResult(ok and not auth_failed, text, 0.0, auth_failed, raw)


def tokens(raw: str) -> int:
    for event in _events(raw):
        if event.get("type") == "result":
            return int((event.get("tokens") or {}).get("total") or 0)
    return 0


# ---------- runs ----------


def run(config: Config, workspace: Path, prompt: str, limits: StageLimits) -> AgentResult:
    """PLAN / BUILD run: the leader skill plus every snapshotted role and skill (H3, H4)."""
    ensure_profile(config)
    cmd = command(config, limits, STAGE_TOOLSETS, skills=exported_skills(config))
    code, raw = execute(cmd, prompt, workspace, build_env(config), limits.timeout_s + 60)
    if code == -1:
        return AgentResult(False, "Agent run timed out", 0.0, False, "")
    if code == 142:  # SIGALRM from the perl timeout wrapper
        return AgentResult(False, f"Agent run exceeded {limits.timeout_s}s", 0.0, False, raw)
    return parse_result(raw)


def probe(config: Config, prompt: str, tool: str, cwd: Path, limits: StageLimits,
          timeout: int) -> StreamSummary:
    """Self-test / verification run with only the probed tool's toolset and no skills."""
    ensure_profile(config)
    cmd = command(config, limits, (PROBE_TOOLSETS[tool],), model=config.hermes_selftest_model or None)
    _, raw = execute(cmd, prompt, cwd, build_env(config), timeout)
    return parse_stream(raw)
