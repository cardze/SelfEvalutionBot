"""Review branch, sensitive-path warning and merge-request text (add-runner-review-branch).

No database: real git on temporary repos, and notify.send / FeedbackService stubbed.
"""

import subprocess
from pathlib import Path

import pytest

from runner import notify, refs
from runner.config import Config

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def _git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A main checkout with `main` plus a branch `auto/x` fetched as refs/runner/x."""
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "runner").mkdir()
    (main / "runner/verify.py").write_text("V = 1\n")
    (main / "bot.py").write_text("B = 1\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    _git(main, "checkout", "-q", "-b", "auto/x")
    (main / "feature.py").write_text("F = 1\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "feat")
    _git(main, "update-ref", "refs/runner/x", "HEAD")
    _git(main, "checkout", "-q", "main")
    _git(main, "branch", "-q", "-D", "auto/x")
    return Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
                  runner_home=tmp_path / "rh", snapshot_home=tmp_path / "snap")


def _commit_on_ref(config, change):
    """Add a commit on top of refs/runner/x that applies `change(main_path)`."""
    main = config.main
    _git(main, "checkout", "-q", "--detach", "refs/runner/x")
    change(main)
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "more")
    _git(main, "update-ref", "refs/runner/x", "HEAD")
    _git(main, "checkout", "-q", "main")


def _rev(config, name):
    return subprocess.run(["git", "-C", str(config.main), "rev-parse", "--verify", "-q", name],
                          capture_output=True, text=True).stdout.strip()


# ---------- sensitive_paths ----------


@pytest.mark.parametrize("path", [
    "runner/agent.py", ".claude/settings.json", ".github/workflows/ci.yml", ".vscode/tasks.json",
    "AGENTS.md", "CLAUDE.md", ".envrc", "requirements.txt", "sql/init.sql",
    "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", ".gitattributes", ".gitmodules",
    "conftest.py", "tests/conftest.py", "a/b/conftest.py",
    "Runner/x.py", ".Claude/settings.json", "agents.md", "Tests/ConfTest.py", "runner/évil.py",
])
def test_sensitive_paths_match(path):
    assert refs.sensitive_paths([path]) == [path]


@pytest.mark.parametrize("path", [
    "bot.py", "runner_notes.md", "docs/AGENTS.md", "tests/test_runner.py", "openspec/changes/x/tasks.md",
    "sql/other.sql", "my_conftest.py", "docs/requirements.txt",
])
def test_sensitive_paths_ignore(path):
    assert refs.sensitive_paths([path]) == []


# ---------- changed_paths ----------


def test_changed_paths_lists_branch_files(repo):
    assert refs.changed_paths(repo, "refs/runner/x") == ["feature.py"]


def test_changed_paths_rename_out_of_runner_is_sensitive(repo):
    def move(main):
        (main / "tools").mkdir()
        _git(main, "mv", "runner/verify.py", "tools/verify.py")
    _commit_on_ref(repo, move)
    paths = refs.changed_paths(repo, "refs/runner/x")
    assert "runner/verify.py" in paths and "tools/verify.py" in paths
    assert refs.sensitive_paths(paths) == ["runner/verify.py"]


def test_changed_paths_non_ascii_is_not_quoted(repo):
    _commit_on_ref(repo, lambda main: (main / "runner/évil.py").write_text("E = 1\n"))
    paths = refs.changed_paths(repo, "refs/runner/x")
    assert "runner/évil.py" in paths
    assert "runner/évil.py" in refs.sensitive_paths(paths)


# ---------- review branch ----------


def test_set_review_branch_points_at_ref(repo):
    assert refs.set_review_branch(repo, "add-x", "refs/runner/x") == ""
    assert _rev(repo, "review/add-x") == _rev(repo, "refs/runner/x")


def test_set_review_branch_overwrites_stale(repo):
    _git(repo.main, "branch", "review/add-x", "main")
    assert refs.set_review_branch(repo, "add-x", "refs/runner/x") == ""
    assert _rev(repo, "review/add-x") == _rev(repo, "refs/runner/x")


def test_delete_review_branch(repo):
    refs.set_review_branch(repo, "add-x", "refs/runner/x")
    assert refs.delete_review_branch(repo, "add-x") == ""
    assert _rev(repo, "review/add-x") == ""
    assert refs.delete_review_branch(repo, "add-x") == ""  # absent: still fine


def test_guard_when_checked_out_in_main(repo):
    refs.set_review_branch(repo, "add-x", "refs/runner/x")
    before = _rev(repo, "review/add-x")
    _git(repo.main, "checkout", "-q", "review/add-x")
    _commit_on_ref(repo, lambda main: (main / "more.py").write_text("M = 1\n"))
    _git(repo.main, "checkout", "-q", "review/add-x")
    assert "checked out" in refs.set_review_branch(repo, "add-x", "refs/runner/x")
    assert "checked out" in refs.delete_review_branch(repo, "add-x")
    assert _rev(repo, "review/add-x") == before


def test_guard_when_checked_out_in_linked_worktree(repo, tmp_path):
    refs.set_review_branch(repo, "add-x", "refs/runner/x")
    _git(repo.main, "worktree", "add", "-q", str(tmp_path / "wt"), "review/add-x")
    assert "checked out" in refs.delete_review_branch(repo, "add-x")
    assert _rev(repo, "review/add-x") != ""


def test_guard_ignores_detached_head(repo):
    refs.set_review_branch(repo, "add-x", "refs/runner/x")
    _git(repo.main, "checkout", "-q", "--detach", "review/add-x")
    assert refs.delete_review_branch(repo, "add-x") == ""


# ---------- merge request text ----------


@pytest.fixture
def sent(monkeypatch):
    messages = []
    monkeypatch.setattr(notify, "send", lambda text, reply_markup=None: messages.append((text, reply_markup)) or 1)
    monkeypatch.setattr(notify.FeedbackService, "update_auto_run", lambda *a, **kw: None)
    return messages


def _merge_request(sensitive):
    notify.merge_request({"id": "r1", "change_name": "add-x"}, {"bug_text": "b", "suggestion_text": "s"},
                         "Summary", "1 file changed", "3 passed", [], "git -C /m diff main...review/add-x",
                         sensitive)


def test_merge_request_lists_sensitive_paths(sent):
    _merge_request(["runner/agent.py", "tests/conftest.py"])
    text, markup = sent[0]
    assert "⚠️ Touches sensitive paths" in text
    assert "runner/agent.py\ntests/conftest.py" in text
    buttons = [b.text for b in markup.inline_keyboard[0]]
    assert buttons == ["✅ Merge", "❌ Reject", "💬 Changes"]


def test_merge_request_omits_section_when_clean(sent):
    _merge_request([])
    assert "sensitive" not in sent[0][0]


def test_merge_request_caps_sensitive_list(sent):
    _merge_request([f"runner/f{i}.py" for i in range(20)])
    text = sent[0][0]
    assert "runner/f14.py" in text and "runner/f15.py" not in text
    assert "…and 5 more" in text


def test_merge_request_review_hint(sent):
    _merge_request([])
    text = sent[0][0]
    assert "diff main...review/add-x" in text
    assert "never check out in the main checkout" in text
