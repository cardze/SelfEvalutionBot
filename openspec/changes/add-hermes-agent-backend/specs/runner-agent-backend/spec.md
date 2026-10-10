## ADDED Requirements

### Requirement: Selectable agent backend
The runner SHALL read `AGENT_BACKEND` from `~/.seb-runner/config.env`. Accepted values are `claude`
and `hermes`; when the key is absent the backend SHALL be `claude`. Any other value SHALL stop the
tick with a configuration error before any agent starts. Every agent run of a tick (self-test, PLAN,
BUILD, sandboxed verification) SHALL use the selected backend.

#### Scenario: Default stays on Claude
- **WHEN** `config.env` has no `AGENT_BACKEND` line
- **THEN** the runner starts agents with `claude -p` exactly as before

#### Scenario: Hermes selected
- **WHEN** `config.env` contains `AGENT_BACKEND=hermes`
- **THEN** the self-test, PLAN, BUILD and verification runs are started with `hermes chat`

#### Scenario: Unknown backend
- **WHEN** `config.env` contains `AGENT_BACKEND=gpt`
- **THEN** the tick fails with an error naming the accepted values and no agent is started

### Requirement: Hermes runs are one-shot, non-interactive and bounded
A Hermes agent run SHALL be started as `hermes chat` with the prompt on standard input, the
`stream-json` output format, `--ignore-rules`, the `tool` session source, a maximum number of turns
and a wall-clock budget taken from the stage limits, and an outer timeout that kills the process.
`HERMES_HOME` SHALL point at the runner's dedicated Hermes profile (default
`~/.hermes/profiles/seb-runner`). PLAN and BUILD runs SHALL enable only the `terminal`, `file`, `todo`
and `delegation` toolsets; self-test and verification runs SHALL enable only the toolset of the tool
under test.

#### Scenario: Run exceeds its time limit
- **WHEN** a Hermes BUILD run is still going after the BUILD timeout
- **THEN** the process is killed and the run is reported as a failed build attempt

#### Scenario: No memory or skill writes
- **WHEN** a runner Hermes run is in progress
- **THEN** the `memory`, `skills`, `web`, `browser` and messaging toolsets are not available to the agent

### Requirement: Agent definitions come from main
Before the first Hermes run of a tick, the runner SHALL export every agent in `main:.claude/agents/`
and every skill in `main:.claude/skills/` into the runner profile as Hermes skills (agents as
`seb-agent-<name>`, skills as `seb-<name>`), replacing the previous export, and SHALL preload all of
them in every PLAN and BUILD run. The workspace's own `AGENTS.md`, `.hermes.md` and project skills
SHALL NOT be loaded.

#### Scenario: Branch edits do not affect the run
- **WHEN** the agent edits `.claude/agents/coder.md` on the run's branch during BUILD
- **THEN** a retried BUILD of the same run still preloads the coder instructions from `main`

### Requirement: Hermes sandbox isolation
Hermes tool execution (terminal, file and code tools) SHALL happen inside a fresh Docker container
per run that has only the workspace mounted, forwards no host environment variables, and is attached
only to an internal network whose sole egress is a proxy allowing `pypi.org` and
`files.pythonhosted.org`. Provider credentials SHALL stay in the profile on the host and SHALL NOT
be visible inside the container. The runner SHALL refuse to start a Hermes run if the rendered
profile configuration does not match these constraints.

#### Scenario: Read of the main checkout
- **WHEN** the agent uses `read_file` or `cat` on a file in the main checkout
- **THEN** the tool fails and the file's contents never appear in the output

#### Scenario: Read of the profile secrets
- **WHEN** the agent runs `wc -c` on the runner profile's `.env`
- **THEN** the command fails

#### Scenario: Write outside the workspace
- **WHEN** the agent writes to `~/.seb-runner/canary-write`
- **THEN** no such file exists on the host afterwards

#### Scenario: Network outside the allowlist
- **WHEN** the agent requests `https://example.com`
- **THEN** the request fails, while `pip install` from PyPI succeeds

#### Scenario: Drifted profile
- **WHEN** the profile's `config.yaml` uses `backend: local` or mounts an extra volume
- **THEN** the runner re-renders it from the template before the run, and fails the run if the
  rendered file still does not pass the check

### Requirement: Self-test before every Hermes run
The isolation self-test SHALL run under the Hermes backend with the same five checks and the same
fail-closed verdicts as for Claude, before the first agent run of a tick. Forbidden content SHALL
include the canary marker and the beginning of every secret value in the runner profile's `.env`.

#### Scenario: Leaked provider key
- **WHEN** any self-test output contains the first characters of a value from the profile `.env`
- **THEN** the self-test fails and no PLAN or BUILD run starts

### Requirement: Verification from raw Hermes tool output
Sandboxed verification under Hermes SHALL run the test suite with a container-local virtual
environment and SHALL decide pass or fail only from the terminal tool's raw output and exit code,
never from the model's reply.

#### Scenario: Model claims success
- **WHEN** the terminal result shows `1 failed, 84 passed` but the model replies "all tests passed"
- **THEN** verification fails with `1 failed, 84 passed`

### Requirement: Backend-specific authentication warning
When a Hermes run fails because the provider rejected its credentials, the runner SHALL record the
failure on the run and send the admin a warning that explains how to re-authenticate the
`seb-runner` Hermes profile, without retrying in the same tick.

#### Scenario: Expired provider key
- **WHEN** a PLAN run's final event carries a 401 / authentication error
- **THEN** the admin receives a ⚠️ message naming `hermes model` for the `seb-runner` profile and the run stays resumable
