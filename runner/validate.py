"""Validate the agent's .auto/output.json and cross-check it against the fetched ref (design D5, D11)."""

import re

from runner import refs
from runner.config import Config

CHANGE_NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_SUMMARY = 1500


class OutputError(Exception):
    pass


def _summary(data: dict) -> str:
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise OutputError("summary is missing")
    return summary.strip()[:MAX_SUMMARY]


def validate_plan(data, config: Config, ref: str) -> dict:
    if not isinstance(data, dict):
        raise OutputError(".auto/output.json is missing, not a regular file, or not a JSON object")
    if data.get("stage") != "planned":
        raise OutputError(f"expected stage 'planned', got {data.get('stage')!r}")
    name = data.get("change_name")
    if not isinstance(name, str) or not CHANGE_NAME.match(name) or len(name) > 100:
        raise OutputError(f"invalid change_name {name!r}")
    if not refs.has_change(config, ref, name):
        raise OutputError(f"openspec/changes/{name}/tasks.md is not committed on the branch")
    return {"change_name": name, "summary": _summary(data)}


def validate_build(data, config: Config, ref: str) -> dict:
    if not isinstance(data, dict):
        raise OutputError(".auto/output.json is missing, not a regular file, or not a JSON object")
    if data.get("stage") != "built":
        raise OutputError(f"expected stage 'built', got {data.get('stage')!r}")
    if refs.commits_ahead(config, ref) == 0:
        raise OutputError("the branch has no commits beyond main")
    return {
        "summary": _summary(data),
        # The requirements.txt diff wins over whatever the agent reported.
        "new_dependencies": refs.added_requirements(config, ref),
    }
