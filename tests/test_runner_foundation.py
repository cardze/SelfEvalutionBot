"""Tests for runner config, template rendering and the run.sh lock (no database, no Claude)."""

import json
import os
import subprocess
from pathlib import Path

import pytest

from runner import config as cfg
from runner import templates

REPO = Path(__file__).resolve().parent.parent


def test_parse_env_file(tmp_path):
    f = tmp_path / "x.env"
    f.write_text('# comment\nexport A=1\nB="two words"\nC=\'3\'\n\nbad line\n')
    assert cfg.parse_env_file(f) == {"A": "1", "B": "two words", "C": "3"}


def test_config_defaults(tmp_path):
    c = cfg.load_config(tmp_path / "missing.env")
    assert c.main == REPO
    assert c.workspace_root == REPO.parent
    assert c.throttle_hours == 5.0
    assert (c.plan.timeout_s, c.plan.budget_usd) == (1200, 2.0)
    assert (c.build.timeout_s, c.build.budget_usd) == (3600, 8.0)
    assert not str(c.snapshot_home).startswith(str(c.runner_home))  # sandbox denies runner_home


def test_config_overrides(tmp_path):
    f = tmp_path / "config.env"
    f.write_text("THROTTLE_HOURS=2\nBUILD_BUDGET_USD=3.5\nWORKSPACE_ROOT=~/ws\n")
    c = cfg.load_config(f)
    assert c.throttle_hours == 2.0
    assert c.build.budget_usd == 3.5
    assert c.workspace_root == Path.home() / "ws"


def test_render_settings_uses_absolute_double_slash(tmp_path):
    c = cfg.Config(main=Path("/Users/x/repo"), workspace_root=Path("/Users/x"),
                   bot_python=Path("/usr/bin/python3"), runner_home=tmp_path)
    settings = json.loads(templates.render_settings(c).read_text())
    reads = [r for r in settings["permissions"]["deny"] if r.startswith("Read(")]
    assert reads and all(r.startswith("Read(//") for r in reads)
    assert "Read(//Users/x/repo/**)" in reads
    sandbox = settings["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert "/Users/x/repo" in sandbox["filesystem"]["denyRead"]
    assert "example.com" not in sandbox["network"]["allowedDomains"]


def test_render_rejects_leftover_placeholder():
    with pytest.raises(ValueError):
        templates.render("{{MAIN}} {{NOPE}}", {"MAIN": "/x"})


def test_plists_render(tmp_path):
    c = cfg.Config(main=REPO, workspace_root=REPO.parent, bot_python=Path("/usr/bin/python3"))
    paths = templates.render_plists(c, tmp_path)
    assert [p.name for p in paths] == ["com.seb.bot.plist", "com.seb.runner.plist"]
    for p in paths:
        assert "{{" not in p.read_text()
        subprocess.run(["plutil", "-lint", str(p)], check=True, capture_output=True)


def test_read_token_requires_prefix(tmp_path):
    c = cfg.Config(main=REPO, workspace_root=REPO.parent, bot_python=Path("/x"), runner_home=tmp_path)
    with pytest.raises(RuntimeError):
        cfg.read_token(c)
    (tmp_path / "oauth_token").write_text("not-a-token")
    with pytest.raises(RuntimeError):
        cfg.read_token(c)


# ---------- run.sh lock ----------


def _run_sh(home: Path):
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "BOT_PYTHON": "/usr/bin/true"}
    return subprocess.run(["/bin/bash", str(REPO / "runner/run.sh")], env=env,
                          capture_output=True, text=True, timeout=30)


def test_lock_held_by_live_process_exits_quietly(tmp_path):
    lock = tmp_path / ".seb-runner/lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text(str(os.getpid()))  # this test process is alive
    assert _run_sh(tmp_path).returncode == 0
    assert (lock / "pid").read_text() == str(os.getpid())  # untouched


def test_stale_lock_is_replaced_and_released(tmp_path):
    lock = tmp_path / ".seb-runner/lock"
    lock.mkdir(parents=True)
    (lock / "pid").write_text("999999")  # not a live pid
    assert _run_sh(tmp_path).returncode == 0
    assert not lock.exists()  # released by the trap after the tick
    assert "removing stale lock" in (tmp_path / ".seb-runner/logs/runner.log").read_text()
