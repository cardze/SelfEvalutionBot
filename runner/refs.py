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


# ---------- review branch (add-runner-review-branch) ----------

# Paths whose changes deserve a close read: they control what runs, and with which trust.
SENSITIVE_PREFIXES = ("runner/", ".claude/", ".github/", ".vscode/")
SENSITIVE_FILES = frozenset({
    "agents.md", "claude.md", ".envrc", "requirements.txt", "sql/init.sql",
    "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", ".gitattributes", ".gitmodules",
})
SENSITIVE_BASENAMES = frozenset({"conftest.py"})


def review_branch(change_name: str) -> str:
    return f"refs/heads/review/{change_name}"


def sensitive_paths(paths) -> list[str]:
    """The paths that match the sensitive list, case-insensitively (the main checkout is on macOS)."""
    found = []
    for path in paths:
        low = path.lower()
        if (low.startswith(SENSITIVE_PREFIXES) or low in SENSITIVE_FILES
                or low.rsplit("/", 1)[-1] in SENSITIVE_BASENAMES):
            found.append(path)
    return found


def changed_paths(config: Config, ref: str) -> list[str]:
    """Files changed on the branch; NUL-separated so no path is quoted, both sides of a rename."""
    out = git_main(config, "diff", "--name-only", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
                   f"main...{ref}")
    return [p for p in out.split("\0") if p]


def _checked_out(config: Config, branch: str) -> bool:
    listing = git_main(config, "worktree", "list", "--porcelain")
    return f"branch {branch}" in listing.splitlines()


def set_review_branch(config: Config, change_name: str, ref: str) -> str:
    """Point review/<name> at ref's commit. Returns '' or a reason it was left alone."""
    branch = review_branch(change_name)
    if _checked_out(config, branch):
        return f"{branch.removeprefix('refs/heads/')} is checked out, so the runner did not move it"
    git_main(config, "update-ref", branch, git_main(config, "rev-parse", "--verify", f"{ref}^{{commit}}"))
    return ""


def delete_review_branch(config: Config, change_name: str) -> str:
    """Delete review/<name> if present. Returns '' or a reason it was left alone."""
    branch = review_branch(change_name)
    if _checked_out(config, branch):
        return f"{branch.removeprefix('refs/heads/')} is checked out, so the runner did not delete it"
    git_main(config, "update-ref", "-d", branch, check=False)
    return ""
