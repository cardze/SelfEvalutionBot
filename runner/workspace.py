"""Per-change workspaces: a local git clone of the main checkout (not a worktree — see design D2)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from runner.config import Config

FORBIDDEN_PREFIXES = ("/tmp/claude", "/private/tmp/claude")  # the sandbox allows writes there
INPUT_FILE = ".auto/input.json"
OUTPUT_FILE = ".auto/output.json"


def short_id(submission_id) -> str:
    return str(submission_id)[:8]


def branch_name(submission_id) -> str:
    return f"auto/{short_id(submission_id)}"


def workspace_path(config: Config, submission_id) -> Path:
    return config.workspace_root / f"SEB-{short_id(submission_id)}"


def assert_safe_location(config: Config, path: Path) -> None:
    resolved = str(path.resolve())
    if resolved.startswith(FORBIDDEN_PREFIXES):
        raise RuntimeError(f"Workspace must not be under /tmp/claude*: {resolved}")
    main = str(config.main.resolve())
    if resolved == main or resolved.startswith(main + "/"):
        raise RuntimeError(f"Workspace must not be inside the main checkout: {resolved}")
    if not path.name.startswith("SEB-"):
        raise RuntimeError(f"Unexpected workspace name: {path.name}")


def git(path: Path, *args: str, check: bool = True) -> str:
    """Only used on a freshly created clone, before any agent has touched it."""
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def create(config: Config, submission_id) -> tuple[Path, str]:
    """Clone main into a fresh workspace on branch auto/<id> and create .venv."""
    path = workspace_path(config, submission_id)
    assert_safe_location(config, path)
    if path.exists():
        raise RuntimeError(f"Workspace already exists: {path}")
    branch = branch_name(submission_id)
    subprocess.run(["git", "clone", "--quiet", "--branch", "main", str(config.main), str(path)],
                   check=True, capture_output=True, text=True)
    git(path, "checkout", "--quiet", "-b", branch)
    (path / ".auto").mkdir(exist_ok=True)
    setup_venv(config, path)
    return path, branch


def setup_venv(config: Config, path: Path) -> None:
    """Create the per-workspace venv and install main's requirements (runs in the trusted runner)."""
    venv = path / ".venv"
    if not venv.exists():
        subprocess.run([str(config.bot_python), "-m", "venv", str(venv)], check=True,
                       capture_output=True, text=True)
    subprocess.run([str(venv / "bin/pip"), "install", "--quiet", "--disable-pip-version-check",
                    "-r", str(path / "requirements.txt"), "pytest"],
                   check=True, capture_output=True, text=True)


def write_input(path: Path, data: dict) -> None:
    """Write input.json without ever following an agent-planted symlink (design D11)."""
    auto = path / ".auto"
    if auto.is_symlink() or (auto.exists() and not auto.is_dir()):
        auto.unlink()
    auto.mkdir(exist_ok=True)
    target = path / INPUT_FILE
    if target.is_symlink() or target.exists():
        target.unlink()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data, default=str, ensure_ascii=False, indent=2))


MAX_OUTPUT_BYTES = 64 * 1024


def read_output(path: Path):
    """Return the parsed output.json, or None if missing, a symlink, oversized or invalid (design D11)."""
    target = path / OUTPUT_FILE
    try:
        if target.is_symlink() or (path / ".auto").is_symlink() or not target.is_file():
            return None
        if target.stat().st_size > MAX_OUTPUT_BYTES:
            return None
        return json.loads(target.read_text())
    except (OSError, ValueError):
        return None


def clear_output(path: Path) -> None:
    (path / OUTPUT_FILE).unlink(missing_ok=True)


def remove(config: Config, path: Path) -> None:
    assert_safe_location(config, path)
    if path.exists():
        shutil.rmtree(path)
