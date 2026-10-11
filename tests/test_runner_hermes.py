"""Tests for the Hermes Agent backend (add-hermes-agent-backend). No Hermes, Docker, Claude or DB."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from runner import agent, hermes, selftest, snapshot, verify
from runner import config as cfg
from runner import runner as rr
from runner.config import Config, StageLimits
from runner.selftest import Check

REPO = Path(__file__).resolve().parent.parent
LIMITS = StageLimits(600, 2.0, 40)


@pytest.fixture
def config(tmp_path):
    return Config(main=REPO, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
                  runner_home=tmp_path / "rh", agent_backend="hermes",
                  hermes_home=tmp_path / "hermes-profile")


def _jsonl(*events):
    return "\n".join(json.dumps(e) for e in events)


def _use(cmd, name="terminal"):
    return {"type": "tool_use", "name": name, "input": {"command": cmd}}


def _term(output, code, error=None):
    return {"type": "tool_result", "name": "terminal", "is_error": code != 0,
            "output": json.dumps({"output": output, "exit_code": code, "error": error})}


def _result(text="DONE", code=0, error=None):
    event = {"type": "result", "exit_code": code, "text": text, "tokens": {"total": 1234}}
    if error:
        event["error"] = error
    return event


# ---------- config ----------


def test_default_backend_is_claude(tmp_path):
    c = cfg.load_config(tmp_path / "missing.env")
    assert c.agent_backend == "claude"
    assert c.hermes_home == Path.home() / ".hermes/profiles/seb-runner"


def test_hermes_keys(tmp_path):
    f = tmp_path / "config.env"
    f.write_text("AGENT_BACKEND=Hermes\nHERMES_HOME=~/hp\nHERMES_MODEL=anthropic/claude-x\n"
                 "HERMES_PROVIDER=openrouter\nHERMES_BIN=/opt/hermes\n")
    c = cfg.load_config(f)
    assert c.agent_backend == "hermes"
    assert c.hermes_home == Path.home() / "hp"
    assert (c.hermes_model, c.hermes_provider, c.hermes_bin) == ("anthropic/claude-x", "openrouter", "/opt/hermes")
    assert c.hermes_config_file == Path.home() / "hp/config.yaml"


def test_unknown_backend_is_an_error(tmp_path):
    f = tmp_path / "config.env"
    f.write_text("AGENT_BACKEND=gpt\n")
    with pytest.raises(ValueError, match="claude, hermes"):
        cfg.load_config(f)


# ---------- command line and environment ----------


def test_stage_command(config):
    c = Config(**{**config.__dict__, "hermes_model": "nous/hermes-5", "hermes_provider": "nous"})
    cmd = hermes.command(c, LIMITS, hermes.STAGE_TOOLSETS, skills=["seb-agent-openspec-leader", "seb-x"])
    assert cmd[:4] == ["perl", "-e", "alarm shift; exec @ARGV", "600"]
    assert cmd[4:7] == ["hermes", "chat", "--query-file"]
    for flag in ("--ignore-rules", "--yolo"):
        assert flag in cmd
    assert cmd[cmd.index("--format") + 1] == "stream-json"
    assert cmd[cmd.index("--source") + 1] == "tool"
    assert cmd[cmd.index("--max-turns") + 1] == "40"
    assert cmd[cmd.index("--run-budget") + 1] == "600"
    assert cmd[cmd.index("-t") + 1] == "terminal,file,todo,delegation"
    assert cmd[cmd.index("-s") + 1] == "seb-agent-openspec-leader,seb-x"
    assert cmd[cmd.index("-m") + 1] == "nous/hermes-5"
    assert cmd[cmd.index("--provider") + 1] == "nous"


def test_probe_command_has_one_toolset_and_no_skills(config):
    cmd = hermes.command(config, LIMITS, (hermes.PROBE_TOOLSETS["Read"],))
    assert cmd[cmd.index("-t") + 1] == "file"
    assert "-s" not in cmd and "-m" not in cmd and "--provider" not in cmd


def test_no_toolset_can_write_memory_or_skills():
    allowed = set(hermes.STAGE_TOOLSETS) | set(hermes.PROBE_TOOLSETS.values())
    assert not allowed & {"memory", "skills", "web", "browser", "session_search", "cronjob", "code_execution"}


def test_env_has_profile_and_no_secrets(config, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:secret")
    monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
    env = hermes.build_env(config)
    assert env["HERMES_HOME"] == str(config.hermes_home)
    assert env["HERMES_IGNORE_RULES"] == "1"
    joined = json.dumps(env)
    assert "secret" not in joined and "POSTGRES" not in joined and "CLAUDE_CODE_OAUTH_TOKEN" not in joined


# ---------- profile ----------


def test_rendered_profile_passes_preflight(config):
    path = hermes.render_profile(config)
    assert path == config.hermes_home / "config.yaml"
    data = json.loads(path.read_text())
    assert data["terminal"]["backend"] == "docker"
    assert data["terminal"]["docker_extra_args"] == ["--network=seb-runner-sandbox"]
    assert "{{" not in path.read_text()
    assert hermes.profile_problems(config) == []


@pytest.mark.parametrize("mutate, problem", [
    (lambda d: d["terminal"].update(backend="local"), "terminal.backend"),
    (lambda d: d["terminal"].update(docker_volumes=["/Users/x:/x"]), "docker_volumes"),
    (lambda d: d["terminal"].update(docker_forward_env=["OPENROUTER_API_KEY"]), "docker_forward_env"),
    (lambda d: d["terminal"].update(docker_extra_args=[]), "network"),
    (lambda d: d["terminal"].update(container_persistent=True), "reused"),
    (lambda d: d["memory"].update(memory_enabled=True), "memory"),
    (lambda d: d["skills"].update(project_discovery=True), "project skills"),
])
def test_preflight_catches_drift(config, mutate, problem):
    path = hermes.render_profile(config)
    data = json.loads(path.read_text())
    mutate(data)
    path.write_text(json.dumps(data))
    problems = hermes.profile_problems(config)
    assert any(problem in p for p in problems), problems


def test_ensure_profile_repairs_drift(config):
    hermes.render_profile(config)
    config.hermes_config_file.write_text("terminal:\n  backend: local\n")
    hermes.ensure_profile(config)
    assert hermes.profile_problems(config) == []


def test_preflight_unreadable(config):
    assert hermes.profile_problems(config)[0].startswith("cannot read")


def test_secret_markers(config):
    config.hermes_home.mkdir(parents=True)
    config.hermes_env_file.write_text("OPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnop\nSHORT=x\n")
    assert hermes.secret_markers(config) == ("sk-or-v1-abc",)


# ---------- parsing ----------


def test_parse_stream_unwraps_terminal_json():
    raw = _jsonl({"type": "system", "subtype": "init"}, _use("cat /x"),
                 _term("cat: /x: No such file or directory", 1), _result())
    s = hermes.parse_stream(raw)
    assert s.calls == [("terminal", "cat /x")]
    assert s.results == [(True, "cat: /x: No such file or directory")]
    assert not s.unsandboxed


def test_parse_stream_nonzero_exit_is_error_even_if_flag_missing():
    event = _term("boom", 2)
    event["is_error"] = False
    assert hermes.parse_stream(_jsonl(_use("x"), event)).results == [(True, "boom")]


def test_parse_stream_file_tool_targets_path():
    raw = _jsonl({"type": "tool_use", "name": "read_file", "input": {"path": "/a/b"}},
                 {"type": "tool_result", "name": "read_file", "is_error": True,
                  "output": "{\"error\": \"File not found\"}"})
    s = hermes.parse_stream(raw)
    assert s.calls == [("read_file", "/a/b")] and s.results[0][0] is True


def test_parse_result_ok_and_failures():
    ok = hermes.parse_result(_jsonl(_use("x"), _result("All done")))
    assert ok.ok and ok.text == "All done" and not ok.auth_failed and ok.cost_usd == 0.0
    failed = hermes.parse_result(_jsonl(_result("", 1, error="iteration budget exhausted")))
    assert not failed.ok and not failed.auth_failed
    auth = hermes.parse_result(_jsonl(_result("", 1, error="Error code: 401 - Unauthorized")))
    assert not auth.ok and auth.auth_failed
    missing = hermes.parse_result("Traceback: No inference provider configured")
    assert not missing.ok and missing.auth_failed
    assert hermes.tokens(_jsonl(_result())) == 1234


def test_parse_result_no_provider_recorded_sample():
    # Recorded from hermes-agent main (2026-10-09) with an empty profile.
    raw = ('{"type": "system", "subtype": "init", "model": "", "session_id": "s1"}\n'
           "Hermes is not connected to any AI provider yet. Run `hermes model` to pick one.\n"
           '{"type": "result", "session_id": "s1", "exit_code": 1, "text": "", "tokens": {"total": 0}, '
           '"error": "credentials or agent init failed"}\n\nsession_id: s1\n')
    result = hermes.parse_result(raw)
    assert not result.ok and result.auth_failed


def test_tool_output_mentioning_401_is_not_an_auth_failure():
    raw = _jsonl(_use("curl x"), _term("HTTP 401 Unauthorized", 1), _result("done"))
    assert hermes.parse_result(raw).ok


# ---------- self-test and verification verdicts on Hermes output ----------


def test_selftest_blocked_call_without_result_passes():
    # Hermes emits tool_use but no tool_result when its own guard blocks a call.
    check = Check("x", "Bash", "cat x", forbidden=("SEB-CANARY-1",))
    assert selftest.verdict(check, hermes.parse_stream(_jsonl(_use("cat x"), _result())))[0] == "pass"


def test_selftest_failed_command_passes():
    check = Check("x", "Bash", "cat x", forbidden=("SEB-CANARY-1",))
    raw = _jsonl(_use("cat x"), _term("No such file", 1))
    assert selftest.verdict(check, hermes.parse_stream(raw))[0] == "pass"


def test_selftest_profile_secret_leak_fails():
    check = Check("x", "Bash", "env", forbidden=("sk-or-v1-abc",))
    raw = _jsonl(_use("env"), _term("OPENROUTER_API_KEY=sk-or-v1-abcdefgh", 1))
    assert selftest.verdict(check, hermes.parse_stream(raw))[0] == "fail"


def test_selftest_success_fails():
    raw = _jsonl(_use("wc -c ~/.hermes/profiles/seb-runner/.env"), _term("88 .env", 0))
    assert selftest.verdict(Check("x", "Bash", "wc"), hermes.parse_stream(raw))[0] == "fail"


def test_selftest_checks_use_hermes_names_and_secret_file(config):
    config.hermes_home.mkdir(parents=True)
    config.hermes_env_file.write_text("NOUS_API_KEY=nous-0123456789abcdef\n")
    checks = selftest.build_checks(config, "SEB-CANARY-1")
    assert "read_file tool" in checks[0].prompt
    assert all("terminal tool" in c.prompt for c in checks[1:])
    assert str(config.hermes_env_file) in checks[2].prompt
    assert all("nous-0123456" in c.forbidden for c in checks)


def test_selftest_checks_unchanged_for_claude(config):
    c = Config(**{**config.__dict__, "agent_backend": "claude"})
    checks = selftest.build_checks(c, "SEB-CANARY-1")
    assert "Read tool" in checks[0].prompt and str(c.token_file) in checks[2].prompt


def _verify_raw(output, code, final="DONE"):
    return _jsonl(_use(hermes.PYTEST_CMD), _term(output, code), _result(final))


def test_verify_pass_from_tail():
    s = hermes.parse_stream(_verify_raw("....\n85 passed, 3 skipped in 1.04s\n", 0))
    v = verify.verdict(s.raw, s)
    assert v.ok and v.summary == "85 passed, 3 skipped"


def test_verify_model_lies():
    s = hermes.parse_stream(_verify_raw("..F\n1 failed, 84 passed in 1.2s\n", 1, final="All tests passed"))
    v = verify.verdict(s.raw, s)
    assert not v.ok and "1 failed" in v.summary


def test_verify_pip_failure():
    s = hermes.parse_stream(_verify_raw("ERROR: Could not find a version that satisfies psycopg", 1))
    assert not verify.verdict(s.raw, s).ok


def test_verify_command_keeps_summary_and_exit_code():
    assert hermes.PYTEST_CMD.startswith("set -o pipefail;")
    assert "pytest -q tests" in hermes.PYTEST_CMD and hermes.PYTEST_CMD.endswith("| tail -n 40")


def test_probe_dispatches_to_hermes(config, monkeypatch):
    seen = {}

    def fake_execute(cmd, prompt, cwd, env, timeout):
        seen.update(cmd=cmd, prompt=prompt, env=env)
        return 0, _verify_raw("3 passed in 0.1s", 0)

    monkeypatch.setattr(hermes, "execute", fake_execute)
    v = verify.run(config, config.workspace_root, None)
    assert v.ok and v.summary == "3 passed"
    assert seen["cmd"][seen["cmd"].index("-t") + 1] == "terminal"
    assert hermes.PYTEST_CMD in seen["prompt"]
    assert seen["env"]["HERMES_HOME"] == str(config.hermes_home)


# ---------- skills snapshot ----------


GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}


def _git(path, *args):
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=GIT_ENV)


def test_export_hermes_skills(tmp_path, monkeypatch):
    for k, v in GIT_ENV.items():
        monkeypatch.setenv(k, v)
    main = tmp_path / "main"
    (main / ".claude/agents").mkdir(parents=True)
    (main / ".claude/skills/openspec-propose/refs").mkdir(parents=True)
    (main / ".claude/agents/openspec-leader.md").write_text(
        "---\nname: openspec-leader\ndescription: Leads: the PM\ntools: Read, Task\n---\nYou lead.\n")
    (main / ".claude/agents/coder.md").write_text("---\nname: coder\ndescription: Codes\n---\nYou code.\n")
    (main / ".claude/skills/openspec-propose/SKILL.md").write_text(
        "---\nname: openspec-propose\ndescription: Propose\n---\nSteps.\n")
    (main / ".claude/skills/openspec-propose/refs/x.md").write_text("ref")
    _git(tmp_path, "init", "-q", "-b", "main", str(main))
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "base")
    (main / ".claude/agents/coder.md").write_text("---\nname: coder\ndescription: Codes\n---\nBRANCH EDIT\n")

    c = Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
               hermes_home=tmp_path / "hp", agent_backend="hermes")
    stale = c.hermes_home / "skills/seb-runner/seb-old/SKILL.md"
    stale.parent.mkdir(parents=True)
    stale.write_text("old")

    names = snapshot.export_hermes_skills(c)
    root = c.hermes_home / "skills/seb-runner"
    assert names == ["seb-agent-coder", "seb-agent-openspec-leader", "seb-openspec-propose"]
    assert not stale.exists()
    leader = (root / "seb-agent-openspec-leader/SKILL.md").read_text()
    assert leader.startswith("---\nname: seb-agent-openspec-leader\ndescription: \"Leads: the PM\"\n---")
    assert "You lead." in leader
    assert "BRANCH EDIT" not in (root / "seb-agent-coder/SKILL.md").read_text()  # snapshot of main
    skill = (root / "seb-openspec-propose/SKILL.md").read_text()
    assert skill.startswith("---\nname: seb-openspec-propose\ndescription: Propose\n---")
    assert (root / "seb-openspec-propose/refs/x.md").read_text() == "ref"
    assert hermes.exported_skills(c) == ["seb-agent-openspec-leader", "seb-agent-coder", "seb-openspec-propose"]


def test_exported_skills_requires_leader(config):
    with pytest.raises(RuntimeError, match="seb-agent-openspec-leader"):
        hermes.exported_skills(config)


def test_repo_snapshot_exports(tmp_path):
    # A git repo of its own: the full suite runs on a `git archive` export with no .git, where a
    # skip would block every merge (runner/testdb.py treats any skip as a failure).
    main = tmp_path / "main"
    shutil.copytree(REPO / ".claude", main / ".claude")
    env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True, env=env)
    c = Config(main=main, workspace_root=tmp_path, bot_python=Path("/usr/bin/python3"),
               hermes_home=tmp_path / "hp", agent_backend="hermes")
    names = snapshot.export_hermes_skills(c)
    assert {"seb-agent-openspec-leader", "seb-agent-planner", "seb-agent-evaluator",
            "seb-agent-coder", "seb-planner-fetch-feedback"} <= set(names)


# ---------- prompts ----------


@pytest.mark.parametrize("backend", ["claude", "hermes"])
def test_prompts_render_without_placeholders(config, backend):
    c = Config(**{**config.__dict__, "agent_backend": backend})
    for name, values in (("plan.md", {"BRANCH": "auto/x"}), ("build.md", {"BRANCH": "auto/x", "CHANGE_NAME": "add-x"})):
        text = rr.render_prompt(c, name, **values)
        assert "{{" not in text
        assert text.startswith("AUTONOMOUS RUNNER RUN")
        assert ("Running on Hermes Agent" in text) == (backend == "hermes")
    build = rr.render_prompt(c, "build.md", BRANCH="b", CHANGE_NAME="n")
    python = "/tmp/seb-venv/bin/python" if backend == "hermes" else ".venv/bin/python"
    assert f"{python} -m pytest -q tests" in build


def test_agent_run_dispatches_to_hermes(config, monkeypatch):
    monkeypatch.setattr(hermes, "run", lambda c, w, p, l: agent.AgentResult(True, "hermes", 0.0, False, ""))
    result = agent.run(config, config.workspace_root, "AUTONOMOUS RUNNER RUN", LIMITS, token=None, agents_json=None)
    assert result.text == "hermes"
