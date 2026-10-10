"""Snapshot agent definitions and skills from `main` (design D5).

Agents become `--agents` JSON (which overrides same-named project agents); skills are exported
to ~/.seb-snapshot/.claude/skills and loaded with `--add-dir`. For the Hermes backend both become
Hermes skills in the runner profile instead (export_hermes_skills). Edits on a run's branch therefore
never affect that run.
"""

import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

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


def _skill_markdown(name: str, description: str, body: str) -> str:
    description = " ".join(description.split())
    return f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n{body.strip()}\n"


def _rename_skill(text: str, name: str) -> str:
    """Rewrite the `name:` line of a SKILL.md frontmatter (or add frontmatter when missing)."""
    if not text.startswith("---"):
        return _skill_markdown(name, name, text)
    _, front, body = text.split("---", 2)
    lines = [line for line in front.strip().splitlines() if not line.startswith("name:")]
    return "---\n" + "\n".join([f"name: {name}", *lines]) + "\n---" + body


def export_hermes_skills(config: Config) -> list[str]:
    """Export main's agents and skills as Hermes skills (add-hermes-agent-backend, design H4).

    .claude/agents/<name>.md → $HERMES_HOME/skills/seb-runner/seb-agent-<name>/SKILL.md
    .claude/skills/<s>/…     → $HERMES_HOME/skills/seb-runner/seb-<s>/…
    The previous export is removed first. Returns the exported skill names.
    """
    from runner.hermes import SKILLS_CATEGORY

    target = config.hermes_home / "skills" / SKILLS_CATEGORY
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    names = []
    for path in _git(config, "ls-tree", "--name-only", "main", ".claude/agents/").split():
        if path.endswith(".md"):
            name, agent = parse_agent_markdown(_git(config, "show", f"main:{path}"))
            skill = f"seb-agent-{name}"
            (target / skill).mkdir()
            (target / skill / "SKILL.md").write_text(_skill_markdown(skill, agent["description"], agent["prompt"]))
            names.append(skill)

    archive = _git(config, "archive", "--format=tar", "main", ".claude/skills", binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            parts = member.name.split("/")
            if not member.isfile() or len(parts) < 4 or ".." in parts:  # .claude/skills/<skill>/<file…>
                continue
            skill = f"seb-{parts[2]}"
            dest = target / skill / Path(*parts[3:])
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = tar.extractfile(member).read()
            if parts[3:] == ["SKILL.md"]:
                data = _rename_skill(data.decode(), skill).encode()
                names.append(skill)
            dest.write_bytes(data)
    if "seb-agent-openspec-leader" not in names:
        raise RuntimeError("main has no openspec-leader agent")
    return sorted(names)
