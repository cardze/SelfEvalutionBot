"""Inspect a run's branch from the main checkout only (design D11).

The workspace's .git/config and hooks are agent-controlled, so the runner never runs git *inside*
the workspace. Instead it fetches the branch into `refs/runner/<id>` in the main checkout and does
every inspection there, under the main checkout's trusted configuration.
"""

import io
import shutil
import subprocess
import tarfile
from pathlib import Path

from runner.config import Config
from runner.workspace import branch_name, short_id

# Defensive flags for every git call: no hooks, no fsmonitor, no external diff/textconv.
SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=always"]


def ref_name(submission_id) -> str:
    return f"refs/runner/{short_id(submission_id)}"


def git_main(config: Config, *args: str, binary: bool = False, check: bool = True):
    result = subprocess.run(["git", *SAFE, "-C", str(config.main), *args],
                            capture_output=True, text=not binary)
    if check and result.returncode != 0:
        err = result.stderr if isinstance(result.stderr, str) else result.stderr.decode(errors="replace")
        raise RuntimeError(f"git {' '.join(args)} failed: {err.strip()}")
    return result.stdout if binary else result.stdout.strip()


def fetch(config: Config, workspace: Path, submission_id) -> str:
    """Fetch auto/<id> from the workspace into refs/runner/<id>; return the ref."""
    ref = ref_name(submission_id)
    git_main(config, "fetch", "--quiet", "--no-tags", str(workspace),
             f"+{branch_name(submission_id)}:{ref}")
    return ref


def commits_ahead(config: Config, ref: str) -> int:
    return int(git_main(config, "rev-list", "--count", f"main..{ref}") or 0)


def diffstat(config: Config, ref: str) -> str:
    return git_main(config, "diff", "--no-ext-diff", "--no-textconv", "--stat", f"main...{ref}") or "(no changes)"


def added_requirements(config: Config, ref: str) -> list[str]:
    """Requirement lines added on the branch — the source of truth for new dependencies."""
    diff = git_main(config, "diff", "--no-ext-diff", "--no-textconv", f"main...{ref}", "--", "requirements.txt")
    lines = []
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            text = line[1:].strip()
            if text and not text.startswith("#"):
                lines.append(text)
    return lines


def has_change(config: Config, ref: str, change_name: str) -> bool:
    result = subprocess.run(
        ["git", *SAFE, "-C", str(config.main), "cat-file", "-e", f"{ref}:openspec/changes/{change_name}/tasks.md"],
        capture_output=True,
    )
    return result.returncode == 0


def export_change(config: Config, ref: str, change_name: str, dest: Path) -> None:
    """Extract openspec/changes/<name> from the ref into dest (a directory that must not exist)."""
    if dest.exists():
        raise RuntimeError(f"Destination already exists: {dest}")
    data = git_main(config, "archive", "--format=tar", ref, f"openspec/changes/{change_name}", binary=True)
    staging = dest.parent / f".{dest.name}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(staging, filter="data")
    shutil.move(str(staging / "openspec/changes" / change_name), str(dest))
    shutil.rmtree(staging, ignore_errors=True)


def delete_ref(config: Config, submission_id) -> None:
    git_main(config, "update-ref", "-d", ref_name(submission_id), check=False)
