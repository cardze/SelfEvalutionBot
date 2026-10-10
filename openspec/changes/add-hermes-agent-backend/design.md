## Context

`runner/` starts four kinds of agent runs, all through `claude -p`:

| Run | Module | Needs |
|-----|--------|-------|
| Isolation self-test (5 forced escapes) | `runner/selftest.py` | raw tool calls + results, one tool per check |
| PLAN / BUILD | `runner/agent.py` via `runner/runner.py` | final text, cost, auth-failure flag |
| Sandboxed pytest | `runner/verify.py` | raw tool output of one pytest command |

Claude-specific pieces: OAuth token (`~/.seb-runner/oauth_token`), `--settings` sandbox file,
`--agents` JSON from `.claude/agents`, `--add-dir` for skills, Claude's stream-json event shape.

Hermes Agent (NousResearch/hermes-agent, checked against `main` of 2026-10-09) offers:
- `hermes chat --query-file - --format stream-json`: one-shot run, JSONL on stdout —
  `{"type":"system","subtype":"init"}`, `text` deltas, `{"type":"tool_use","name","input"}`,
  `{"type":"tool_result","name","output","is_error"}`, and a final
  `{"type":"result","exit_code","text","tokens","error"?}`. Tool outputs are capped at 5000 chars.
  A call blocked by Hermes's own guards emits `tool_use` with no `tool_result`.
- `--max-turns N`, `--run-budget SECONDS`, `-t/--toolsets`, `-s/--skills`, `--ignore-rules`
  (no AGENTS.md / .hermes.md / memory / auto-loaded skills; explicit `-s` still loads), `--yolo`,
  `-m/--provider`, `--source tool` (keeps runs out of the user's session list).
- Profiles: any `HERMES_HOME` directory; `~/.hermes/profiles/<name>` is listed by
  `hermes profile list` and by the `hermes dashboard` web UI (port 9119).
- Terminal backends. With `terminal.backend: docker`, **terminal, file and execute_code tools** all
  run via `docker exec` in a hardened container (caps dropped, no-new-privileges, PID limits).
  `docker_mount_cwd_to_workspace: true` bind-mounts the launch directory at `/workspace`;
  `container_persistent: false` + `docker_persist_across_processes: false` give one fresh container
  per run; `docker_extra_args` is appended last to `docker run`.
- No dollar budget flag; cost is not in the stream (token counts are).

## Goals / Non-Goals

Goals: run every runner agent step on Hermes with guarantees equivalent to `runner-isolation`;
keep the trusted runner logic (stages, validation, refs, merge, notify) backend-agnostic; keep
Claude as default and fallback. Non-goals: see proposal.

## Decisions

### H1. Backend switch in `config.env`, default `claude`
`AGENT_BACKEND` (`claude`|`hermes`, anything else is a config error). Default stays `claude` so the
hourly launchd job keeps working after this merges; `runner/setup.sh use-backend hermes` writes the
line after Hermes is set up. Other keys: `HERMES_BIN` (default `hermes` on PATH),
`HERMES_HOME` (default `~/.hermes/profiles/seb-runner`), `HERMES_MODEL`, `HERMES_PROVIDER`
(optional; otherwise the profile's `model:` section), `SELFTEST_MODEL` is ignored by Hermes unless
`HERMES_SELFTEST_MODEL` is set.

### H2. One dispatch point: `runner/agent.py`
`agent.run()` (PLAN/BUILD) and a new `agent.probe(config, prompt, tool, cwd, secret, model)`
(self-test checks and verification) dispatch on `config.agent_backend`. `probe` returns the
normalised `StreamSummary` (calls, results, unsandboxed flag, raw) that `selftest.verdict` and
`verify.verdict` already consume, so the verdict logic is shared. Hermes specifics live in
`runner/hermes.py`: command line, environment, JSONL → `StreamSummary` / `AgentResult`, skills
snapshot, and the Hermes-specific prompt values.

### H3. The Hermes command
```
perl -e 'alarm shift; exec @ARGV' <timeout> \
  hermes chat --query-file - --format stream-json --source tool \
    --ignore-rules --yolo --max-turns <N> --run-budget <timeout> \
    -t <toolsets> [-s <skills>] [-m <model>] [--provider <p>]
```
The prompt goes on stdin (no shell or argv quoting issues). Stage toolsets:
`terminal,file,todo,delegation`; probes get only the toolset of the probed tool
(`Bash`→`terminal`, `Read`→`file`). `--yolo` is required because there is no TTY to approve
prompts; it is safe only because tools run in the container (H5) — Hermes's hard-line blocks still
apply. `--ignore-rules` keeps the workspace's (agent-editable) `AGENTS.md` out of the system prompt;
the main snapshot's instructions arrive as skills instead (H4).

### H4. Agent definitions and skills become Hermes skills, snapshotted from `main`
Before each tick's first run, `snapshot.export_hermes_skills` rewrites
`$HERMES_HOME/skills/seb-runner/` from `git archive main`:
- each `.claude/agents/<name>.md` → `seb-agent-<name>/SKILL.md` (frontmatter `name`,
  `description`; body = agent prompt),
- each `.claude/skills/<s>/` → `seb-<s>/` (its `SKILL.md` frontmatter `name` rewritten to `seb-<s>`).
All of them are preloaded with `-s`. The leader runs as `seb-agent-openspec-leader`; the Hermes prompt
appendix (`runner/prompts/hermes.md`) tells it to delegate to planner/evaluator/coder with
`delegate_task`, passing that role skill's instructions in the task context. Edits on the run's
branch therefore never affect the run, as in design D5 of the original runner.

### H5. Sandbox = Docker backend + internal network + allowlisting proxy
`runner/hermes/config.template.yaml` is rendered to `$HERMES_HOME/config.yaml` by
`runner/setup.sh hermes-profile` (and re-rendered by every tick, so a drifted profile is repaired):
```yaml
terminal:
  backend: docker
  cwd: /workspace
  docker_image: seb-runner-sandbox:latest      # built from runner/hermes/Dockerfile
  docker_mount_cwd_to_workspace: true
  docker_run_as_host_user: true
  container_persistent: false
  docker_persist_across_processes: false
  docker_forward_env: []
  docker_volumes: []
  docker_extra_args: ["--network=seb-runner-sandbox"]
  docker_env: {HTTPS_PROXY/HTTP_PROXY → http://seb-runner-egress:3128, git identity, GIT_CONFIG_GLOBAL=/dev/null, safe.directory=/workspace}
memory: {memory_enabled: false, user_profile_enabled: false, nudge_interval: 0}
skills: {project_discovery: false, auto_load: [], inline_shell: false}
curator: {enabled: false}
auxiliary.background_review.enabled: false
```
`seb-runner-sandbox` is a Docker network created with `--internal` (no route out). The only other
member is `seb-runner-egress`, a Squid container also attached to the default bridge, whose
`runner/hermes/squid.conf` allows `CONNECT` to `pypi.org` and `files.pythonhosted.org` only.
So the container can reach PyPI through the proxy and nothing else; host paths (main checkout,
`~/.seb-runner`, `~/.hermes`, `~/.ssh`, …) do not exist inside it. Provider API keys stay in
`$HERMES_HOME/.env` on the host and are used only by the Hermes host process for model calls; they
are never forwarded into the container.

The rendered `config.yaml` lives outside the workspace; nothing in the workspace can change it.
Hermes would otherwise load "project skills" from `/.hermes/skills` in a trusted repo —
`project_discovery: false` turns that off.

### H6. Python inside the container
The host's `.venv` (macOS) cannot run in the Linux container. For Hermes, prompts use a
container-local venv: `python3 -m venv /tmp/seb-venv && /tmp/seb-venv/bin/pip install -q -r
requirements.txt pytest`, then `/tmp/seb-venv/bin/python -m pytest …`. Build prompt placeholders
`{{VENV_SETUP}}`, `{{PYTHON}}`, `{{PIP}}` are filled per backend (Claude keeps `.venv/bin/...`).
Verification runs in a fresh container, so `/tmp/seb-venv` is never agent-planted; its command is
`set -o pipefail; <setup> && /tmp/seb-venv/bin/python -m pytest -q tests 2>&1 | tail -n 40`
so the pytest summary survives Hermes's 5000-char output cap. The terminal tool's output is a JSON
object (`output`, `exit_code`); the parser unwraps it, and a non-zero `exit_code` is an error.

### H7. Self-test unchanged in spirit, adapted in detail
Same five checks and fail-closed rules. Differences: the secret file probed is `$HERMES_HOME/.env`
(the Claude token file when the backend is Claude); the leak markers include the first 12 chars of
every value in that `.env`; tool names in the prompts are Hermes's (`read_file`, `terminal`);
`dangerouslyDisableSandbox` has no Hermes equivalent, so `unsandboxed` stays false. Additionally a
**pre-flight** refuses to start any Hermes run unless the rendered profile still says
`backend: docker`, mounts no volumes, forwards no env, and includes `--network=seb-runner-sandbox`.

### H8. Results, cost and auth failures
`AgentResult.ok` = final `result` event with `exit_code == 0` and no `error`. `cost_usd` is 0.0
(Hermes reports tokens, logged instead). Auth failure markers: `401`, `Unauthorized`,
`AuthenticationError`, `invalid_api_key`, `No API key`, `No inference provider`. The Telegram
warning for an auth failure names the backend's own fix (`hermes model` / `hermes auth` for the
`seb-runner` profile instead of `claude setup-token`).

## Risks / Trade-offs

- **Docker is required** on the runner host (Docker Desktop on macOS). Mitigation: setup command,
  self-test fails closed if Docker or the network is missing.
- **No dollar cap** per stage with Hermes; limits are turns and wall-clock only. Mitigation: admin
  sets provider spend limits; README says so.
- **Hermes evolves fast** (flags, event shape). Mitigation: all Hermes-specific parsing is in one
  module with recorded-sample tests; the self-test exercises the real binary before every run.
- **Bind mount means container writes land in the workspace** — intended; that is also true of the
  Claude sandbox.
- **Squid image pulled from Docker Hub** at setup; pinned tag in `setup.sh`.

## Migration Plan

1. Install Hermes (`curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash`).
2. `runner/setup.sh hermes-profile` → creates the `seb-runner` profile and renders its config;
   then `HERMES_HOME=~/.hermes/profiles/seb-runner hermes model` to pick provider/model and log in.
3. `runner/setup.sh hermes-sandbox` → builds the sandbox image, creates the internal network and
   starts the egress proxy.
4. `runner/setup.sh use-backend hermes && runner/setup.sh selftest` → must print SELFTEST PASSED.
5. Rollback: `runner/setup.sh use-backend claude`.
