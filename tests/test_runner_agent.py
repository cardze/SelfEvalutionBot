"""Tests for agent snapshotting, output validation and the agent environment (no Claude, no DB)."""

import json
import subprocess
from pathlib import Path

import pytest

from runner import agent, refs, snapshot, validate
from runner import workspace as ws
from runner.config import Config, StageLimits

REPO = Path(__file__).resolve().parent.parent


# ---------- snapshot ----------


def test_parse_agent_markdown_maps_task_to_agent():
    name, a = snapshot.parse_agent_markdown(
        "---\nname: lead\ndescription: Leads\ntools: Read, Bash, Task\n---\nYou lead.\n"
    )
    assert name == "lead"
    assert a == {"description": "Leads", "prompt": "You lead.", "tools": ["Read", "Bash", "Task", "Agent"]}


def test_parse_agent_markdown_requires_frontmatter():
    with pytest.raises(ValueError):
        snapshot.parse_agent_markdown("no frontmatter")
    with pytest.raises(ValueError):
        snapshot.parse_agent_markdown("---\nname: x\n---\nbody")  # no description


def test_repo_agents_parse():
    for path in (REPO / ".claude/agents").glob("*.md"):
        name, a = snapshot.parse_agent_markdown(path.read_text())
        assert name and a["prompt"]


# ---------- fetch-based inspection + validation (temp repos, design D11) ----------

SUB = "abc12345-0000-0000-0000-000000000000"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin:/opt/homebrew/bin"}


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=GIT_ENV)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "requirements.txt").write_text("psycopg==3.1.12\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    workspace = tmp_path / "SEB-abc12345"
    subprocess.run(["git", "clone", "-q", str(main), str(workspace)], check=True, env=GIT_ENV)
    _git(workspace, "checkout", "-q", "-b", "auto/abc12345")
    config = Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"))
    return config, workspace


def test_validate_plan(setup):
    config, workspace = setup
    ref = refs.fetch(config, workspace, SUB)
    with pytest.raises(validate.OutputError):
        validate.validate_plan(None, config, ref)
    with pytest.raises(validate.OutputError):
        validate.validate_plan({"stage": "planned", "change_name": "Bad Name", "summary": "x"}, config, ref)
    (workspace / "openspec/changes/add-x").mkdir(parents=True)
    (workspace / "openspec/changes/add-x/tasks.md").write_text("- [ ] 1.1 do it\n")
    with pytest.raises(validate.OutputError):  # exists on disk but not committed
        validate.validate_plan({"stage": "planned", "change_name": "add-x", "summary": "x"}, config, ref)
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "plan")
    ref = refs.fetch(config, workspace, SUB)
    assert validate.validate_plan({"stage": "planned", "change_name": "add-x", "summary": " s "}, config, ref) == {
        "change_name": "add-x", "summary": "s"}


def test_validate_build_requires_commits(setup):
    config, workspace = setup
    ref = refs.fetch(config, workspace, SUB)
    with pytest.raises(validate.OutputError):
        validate.validate_build({"stage": "built", "summary": "done"}, config, ref)


def test_dependencies_and_diffstat_come_from_fetched_ref(setup):
    config, workspace = setup
    (workspace / "requirements.txt").write_text("psycopg==3.1.12\npython-telegram-bot[job-queue]==20.7\n")
    _git(workspace, "commit", "-q", "-am", "feat")
    (workspace / "requirements.txt").write_text("uncommitted-extra==1.0\n")  # never fetched
    ref = refs.fetch(config, workspace, SUB)
    out = validate.validate_build({"stage": "built", "summary": "done", "new_dependencies": []}, config, ref)
    assert out["new_dependencies"] == ["python-telegram-bot[job-queue]==20.7"]
    assert "requirements.txt" in refs.diffstat(config, ref)


def test_workspace_hooks_and_fsmonitor_never_run(setup, tmp_path):
    config, workspace = setup
    pwned = tmp_path / "PWNED"
    script = tmp_path / "evil.sh"
    script.write_text(f"#!/bin/sh\ntouch {pwned}\n")
    script.chmod(0o755)
    for hook in ("post-checkout", "pre-commit", "post-merge", "reference-transaction", "pre-push"):
        (workspace / ".git/hooks" / hook).write_text(f"#!/bin/sh\ntouch {pwned}\n")
        (workspace / ".git/hooks" / hook).chmod(0o755)
    _git(workspace, "config", "core.fsmonitor", str(script))
    _git(workspace, "config", "core.hooksPath", str(workspace / ".git/hooks"))
    (workspace / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(workspace), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                    "add", "a.txt"], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(workspace), "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
                    "commit", "-q", "-m", "x"], check=True, env=GIT_ENV)
    assert not pwned.exists()  # setup itself did not trigger anything

    ref = refs.fetch(config, workspace, SUB)
    refs.commits_ahead(config, ref)
    refs.diffstat(config, ref)
    refs.added_requirements(config, ref)
    refs.has_change(config, ref, "nothing")
    assert not pwned.exists()


def test_export_change(setup, tmp_path):
    config, workspace = setup
    (workspace / "openspec/changes/add-x").mkdir(parents=True)
    (workspace / "openspec/changes/add-x/proposal.md").write_text("why")
    (workspace / "openspec/changes/add-x/tasks.md").write_text("- [ ] 1")
    _git(workspace, "add", "-A")
    _git(workspace, "commit", "-q", "-m", "plan")
    ref = refs.fetch(config, workspace, SUB)
    dest = tmp_path / "archive" / "2026-09-25-add-x"
    dest.parent.mkdir()
    refs.export_change(config, ref, "add-x", dest)
    assert (dest / "proposal.md").read_text() == "why"


def test_read_output_refuses_symlink_and_oversize(tmp_path):
    (tmp_path / ".auto").mkdir()
    secret = tmp_path / "secret.json"
    secret.write_text('{"stage": "planned"}')
    (tmp_path / ".auto/output.json").symlink_to(secret)
    assert ws.read_output(tmp_path) is None
    (tmp_path / ".auto/output.json").unlink()
    (tmp_path / ".auto/output.json").write_text('{"summary": "' + "x" * 70000 + '"}')
    assert ws.read_output(tmp_path) is None
    (tmp_path / ".auto/output.json").write_text('{"stage": "built"}')
    assert ws.read_output(tmp_path) == {"stage": "built"}


def test_write_input_does_not_follow_symlinks(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    (tmp_path / ".auto").mkdir()
    (tmp_path / ".auto/input.json").symlink_to(victim)
    ws.write_input(tmp_path, {"a": 1})
    assert victim.read_text() == "original"
    assert json.loads((tmp_path / ".auto/input.json").read_text()) == {"a": 1}
    # .auto itself replaced by a symlink to another directory
    other = tmp_path / "other"
    other.mkdir()
    import shutil
    shutil.rmtree(tmp_path / ".auto")
    (tmp_path / ".auto").symlink_to(other)
    ws.write_input(tmp_path, {"b": 2})
    assert not (other / "input.json").exists()


def test_workspace_location_guards(tmp_path):
    c = Config(main=REPO, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"))
    with pytest.raises(RuntimeError):
        ws.assert_safe_location(c, Path("/private/tmp/claude-501/SEB-x"))
    with pytest.raises(RuntimeError):
        ws.assert_safe_location(c, REPO / "SEB-x")
    with pytest.raises(RuntimeError):
        ws.assert_safe_location(c, tmp_path / "not-a-workspace")
    ws.assert_safe_location(c, Path.home() / "github/SEB-abc12345")


# ---------- agent environment and command ----------


def test_agent_env_contains_no_production_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prod-bot-token")
    monkeypatch.setenv("POSTGRES_PASSWORD", "prod-db-password")
    c = Config(main=REPO, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"))
    env = agent.build_env(c, tmp_path / "SEB-x", "sk-ant-oat01-token")
    values = " ".join(env.values())
    assert "prod-bot-token" not in values and "prod-db-password" not in values
    assert "TELEGRAM_BOT_TOKEN" not in env
    assert not any(k.startswith("POSTGRES_") for k in env)  # no database inside the sandbox
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert env["PATH"].startswith(str(tmp_path / "SEB-x/.venv/bin"))


def test_claude_command_flags(tmp_path):
    c = Config(main=REPO, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
               runner_home=tmp_path / "rh", snapshot_home=tmp_path / "snap")
    cmd = agent.claude_command(c, "PROMPT", StageLimits(60, 1.5, 10), agents_json="{}", agent="openspec-leader")
    assert cmd[:4] == ["perl", "-e", "alarm shift; exec @ARGV", "60"]
    joined = " ".join(cmd)
    for flag in ("--setting-sources user", "--max-budget-usd 1.5", "--max-turns 10",
                 "--agent openspec-leader", "--output-format json"):
        assert flag in joined
    assert "--settings" in cmd and str(c.settings_file) in cmd
    assert "--add-dir" not in cmd  # snapshot dir does not exist


def test_parse_result_detects_auth_failure():
    raw = json.dumps({"type": "result", "is_error": True,
                      "result": "Failed to authenticate: OAuth session expired", "total_cost_usd": 0})
    r = agent.parse_result(raw)
    assert r.auth_failed and not r.ok


def test_parse_result_success():
    r = agent.parse_result(json.dumps({"type": "result", "is_error": False, "result": "done",
                                       "total_cost_usd": 0.42}))
    assert r.ok and r.text == "done" and r.cost_usd == 0.42
