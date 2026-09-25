"""Snapshot agent definitions and skills from `main` (design D5).

Agents become `--agents` JSON (which overrides same-named project agents); skills are exported
to ~/.seb-snapshot/.claude/skills and loaded with `--add-dir`. Edits on a run's branch therefore
never affect that run.
"""

import io
import json
import shutil
import subprocess
import tarfile

from runner.config import Config


def _git(config: Config, *args: str, binary: bool = False):
    result = subprocess.run(["git", "-C", str(config.main), *args], check=True, capture_output=True,
                            text=not binary)
    return result.stdout


def parse_agent_markdown(text: str) -> tuple[str, dict]:
    """Split '---\\nfrontmatter\\n---\\nbody' into (name, agent definition)."""
    if not text.startswith("---"):
        raise ValueError("Agent file has no frontmatter")
    _, front, body = text.split("---", 2)
    meta = {}
    for line in front.strip().splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"').strip("'")
    name = meta.get("name")
    if not name or not meta.get("description"):
        raise ValueError("Agent frontmatter needs name and description")
    agent = {"description": meta["description"], "prompt": body.strip()}
    if meta.get("tools"):
        tools = [t.strip() for t in meta["tools"].split(",") if t.strip()]
        if "Task" in tools and "Agent" not in tools:
            tools.append("Agent")  # current name of the delegation tool; keep the legacy name too
        agent["tools"] = tools
    if meta.get("model"):
        agent["model"] = meta["model"]
    return name, agent


def agents_json(config: Config) -> str:
    files = _git(config, "ls-tree", "--name-only", "main", ".claude/agents/").split()
    agents = {}
    for path in files:
        if path.endswith(".md"):
            name, agent = parse_agent_markdown(_git(config, "show", f"main:{path}"))
            agents[name] = agent
    if "openspec-leader" not in agents:
        raise RuntimeError("main has no openspec-leader agent")
    return json.dumps(agents)


def export_skills(config: Config) -> None:
    target = config.snapshot_home / ".claude"
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    archive = _git(config, "archive", "--format=tar", "main", ".claude/skills", binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(config.snapshot_home, filter="data")
