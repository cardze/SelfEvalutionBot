"""Tests for runner/guard.py (change guard-hermes-from-runner). Real git on temporary repos, no database."""

import dataclasses
import json
import subprocess
from pathlib import Path

import pytest

from runner import guard, selftest, templates
from runner import runner as rr
from runner.config import Config, load_config

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    (main / "hermes_plugin/seb").mkdir(parents=True)
    (main / "hermes_plugin/seb/__init__.py").write_text("x = 1\n")
    (main / "runner").mkdir()
    (main / "runner/runner.py").write_text("x = 1\n")
    (main / "bot.py").write_text("x = 1\n")
    (main / "requirements.txt").write_text("psycopg==3.1.12\n")
    _git(main, "init", "-q", "-b", "main")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    _git(main, "checkout", "-q", "-b", "auto/x")
    return Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"))


def _commit(config, files):
    for name, text in files.items():
        path = config.main / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    _git(config.main, "add", "-A")
    _git(config.main, "commit", "-q", "-m", "change")
    return "auto/x"


HERMES = dict(bot_service="hermes")


@pytest.mark.parametrize("path, launchd, hermes", [
    ("bot.py", False, False),
    ("feature.py", False, False),
    ("hermes_bot.py", True, True),
    ("Hermes_Bot.py", True, True),
    ("hermes_plugin/seb/plugin.yaml", True, True),
    ("hermes_profile/setup.sh", True, True),
    ("HERMES_PROFILE/SOUL.md", True, True),
    ("runner/hermes.py", True, True),
    ("tests/test_hermes_bot.py", True, True),
    ("docs/hermes.md", True, True),
    ("runner/runner.py", False, True),
    ("Runner/guard.py", False, True),
    ("requirements.txt", False, True),
    ("openspec/changes/x/hermes-notes.md", False, False),
])
def test_protected_paths(path, launchd, hermes):
    assert bool(guard.protected_paths([path], "launchd")) is launchd
    assert bool(guard.protected_paths([path], "hermes")) is hermes


def test_clean_bot_change_passes(repo):
    ref = _commit(repo, {"bot.py": "x = 2\n", "feature.py": "def f():\n    return 1\n"})
    assert guard.violations(repo, ref) == []
    assert guard.violations(dataclasses.replace(repo, **HERMES), ref) == []


def test_plugin_change_refused_in_both_modes(repo):
    ref = _commit(repo, {"hermes_plugin/seb/__init__.py": "x = 2\n"})
    for config in (repo, dataclasses.replace(repo, **HERMES)):
        [reason] = guard.violations(config, ref)
        assert "protected paths changed: hermes_plugin/seb/__init__.py" in reason


def test_requirements_only_refused_in_hermes_mode(repo):
    ref = _commit(repo, {"requirements.txt": "psycopg==3.1.12\nrequests==2.0\n"})
    assert guard.violations(repo, ref) == []
    assert "requirements.txt" in guard.violations(dataclasses.replace(repo, **HERMES), ref)[0]


def test_rename_out_of_protected_path_is_refused(repo):
    _git(repo.main, "mv", "hermes_plugin/seb/__init__.py", "shim.py")
    _git(repo.main, "commit", "-q", "-m", "move")
    assert "hermes_plugin/seb/__init__.py" in guard.violations(repo, "auto/x")[0]


def test_added_code_mentioning_hermes_is_refused(repo):
    ref = _commit(repo, {"bot.py": 'from pathlib import Path\nCFG = Path.home() / ".Hermes" / "config.yaml"\n'})
    [reason] = guard.violations(repo, ref)
    assert reason.startswith("added code mentions Hermes: bot.py:")
    assert ".Hermes" in reason


def test_hermes_mentions_allowed_in_openspec_and_markdown(repo):
    ref = _commit(repo, {"openspec/changes/x/design.md": "Hermes gateway\n",
                         "openspec/changes/x/tasks.yaml": "hermes: no\n",
                         "README.md": "Runs on Hermes\n", "docs/Guide.MD": "hermes\n"})
    assert guard.violations(repo, ref) == []


def test_removed_lines_mentioning_hermes_are_fine(repo):
    _commit(repo, {"bot.py": "# hermes\n"})
    _git(repo.main, "checkout", "-q", "main")
    _git(repo.main, "merge", "-q", "auto/x")
    _git(repo.main, "checkout", "-q", "auto/x")
    assert guard.violations(repo, _commit(repo, {"bot.py": "x = 3\n"})) == []


def test_describe_and_report_limit(repo):
    ref = _commit(repo, {f"hermes_{i}.py": "x = 1\n" for i in range(7)})
    [reason] = guard.violations(repo, ref)
    assert reason.endswith("(+2 more)")
    assert guard.describe([reason]).startswith(guard.NEEDS_A_PERSON)


def test_prompts_state_the_rule(repo):
    (repo.main / "runner/prompts").mkdir()
    for name in ("plan.md", "build.md"):
        (repo.main / "runner/prompts" / name).write_text(
            (Path(__file__).resolve().parent.parent / "runner/prompts" / name).read_text())
        launchd = rr.render_prompt(repo, name, BRANCH="b", CHANGE_NAME="c")
        hermes = rr.render_prompt(dataclasses.replace(repo, **HERMES), name, BRANCH="b", CHANGE_NAME="c")
        assert "{{" not in launchd and "`hermes_plugin/`" in launchd and "`requirements.txt`" not in launchd.split("## Rules")[1]
        assert "`runner/` or `requirements.txt`" in hermes


@pytest.mark.parametrize("profile", ["default", "Seb", "../x", "-p"])
def test_hermes_profile_must_be_a_plain_non_default_name(tmp_path, profile):
    env = tmp_path / "config.env"
    env.write_text(f"HERMES_PROFILE={profile}\n")
    with pytest.raises(ValueError, match="HERMES_PROFILE"):
        load_config(env)


def test_settings_deny_hermes_home(tmp_path):
    c = Config(main=Path("/Users/x/repo"), workspace_root=Path("/Users/x"),
               bot_python=Path("/usr/bin/python3"), runner_home=tmp_path)
    settings = json.loads(templates.render_settings(c).read_text())
    home = Path.home()
    assert f"Read(/{home}/.hermes/**)" in settings["permissions"]["deny"]
    assert f"{home}/.hermes" in settings["sandbox"]["filesystem"]["denyRead"]


def test_selftest_checks_hermes_home(tmp_path):
    c = Config(main=tmp_path, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"), runner_home=tmp_path)
    [check] = [ch for ch in selftest.build_checks(c, "M") if ch.name == "bash read Hermes home"]
    assert str(Path.home() / ".hermes") in check.prompt
