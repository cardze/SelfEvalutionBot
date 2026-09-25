# runner-isolation Specification

## Purpose
Guarantee that unattended agent runs cannot reach secrets, the main checkout, the database or the wider network, and that the runner never executes unapproved agent-controlled code outside the sandbox. This is verified by a self-test before every run.
## Requirements
### Requirement: Secrets never reach the agent
The agent process SHALL be started with a freshly built environment. It SHALL NOT contain:
- the bot token
- the production database credentials
- any variable from the main checkout's `.env`

The OAuth token SHALL be passed only as `CLAUDE_CODE_OAUTH_TOKEN` to the `claude` process. The agent SHALL receive no database credentials.

#### Scenario: Agent inspects its environment
- **WHEN** the agent runs `env` in Bash
- **THEN** the output contains neither the bot token, nor any `POSTGRES_*` value, nor `CLAUDE_CODE_OAUTH_TOKEN`

### Requirement: Runner-supplied permissions and sandbox
Agent runs SHALL use `--setting-sources user` and `--settings` pointing to the runner settings file rendered from `runner/settings.template.json`. That file SHALL contain:
- **permission deny rules**, with `//` absolute paths, for the main checkout, `~/.seb-runner`, `~/.ssh`, `~/.aws` and `~/.config`, plus deny rules for `git push` and `git remote`
- **sandbox settings**: `enabled: true`, `allowUnsandboxedCommands: false`, `filesystem.denyRead` for the same paths, and `network.allowedDomains` limited to PyPI (no database access)

Settings in the workspace SHALL have no effect.

#### Scenario: Read tool on protected path
- **WHEN** the agent uses the Read tool on a file in the main checkout
- **THEN** the tool returns a permission-denied error

#### Scenario: Bash read of protected path
- **WHEN** the agent runs `cat` or `wc` on `~/.seb-runner/oauth_token`
- **THEN** the command fails with `Operation not permitted`, and no retry outside the sandbox occurs

#### Scenario: Write outside workspace
- **WHEN** the agent writes to a path outside its workspace
- **THEN** the write fails and no file is created

#### Scenario: Network outside allowlist
- **WHEN** the agent requests `https://example.com`
- **THEN** the request is blocked, while requests to `pypi.org` succeed

#### Scenario: Workspace settings ignored
- **WHEN** the workspace contains `.claude/settings.json` with permissive allow rules or `.claude/agents/` definitions
- **THEN** neither affects the agent run

### Requirement: Agent definitions from main
Agent definitions SHALL be taken from `main` at run time and passed via `--agents` JSON, with the main agent selected by `--agent openspec-leader`. Skills SHALL be snapshotted from `main` into a directory outside `~/.seb-runner/` and loaded via `--add-dir`. Edits to agents or skills on a run's branch SHALL NOT affect that run.

#### Scenario: Branch edits an agent
- **WHEN** a run's branch modifies `.claude/agents/coder.md`
- **THEN** the run's agents still behave per `main`'s version, until the change is merged

### Requirement: Self-test before every agent run
Before each agent run, the runner SHALL run a self-test under the same settings, working directory and environment as the real run. It SHALL force the following attempts and inspect the raw tool results:
- a Read-tool read and a Bash read of a canary file in the main checkout
- a Bash read of the token file, measured with `wc -c` only
- a Bash write outside the workspace
- a request to a non-allowlisted domain

Any leak, write, unsandboxed retry, or allowed request SHALL abort the run, record `last_error`, and notify the admin.

#### Scenario: Self-test passes
- **WHEN** all forced attempts fail as expected, and no canary marker or `sk-ant` string appears in any output
- **THEN** the real agent run starts

#### Scenario: Self-test detects a leak
- **WHEN** any forced attempt succeeds
- **THEN** the real agent run does not start, and the admin receives a ⚠️ message naming the failed check

#### Scenario: Inconclusive self-test
- **WHEN** the self-test model makes no tool call for a check, both on the first try and on one retry
- **THEN** the self-test is treated as failed

### Requirement: No database access from the sandbox
Agent runs and sandboxed verifications SHALL have no database access: no `POSTGRES_*` settings, and Postgres unreachable over both TCP and the Unix socket. Database-backed tests SHALL run only in the post-approval full-suite run, after the admin taps ✅, against a throwaway database created and dropped by the runner, on exactly the approved commit, in a fresh venv, and with an environment that holds no bot token.

#### Scenario: Agent tries the production database
- **WHEN** the agent runs `psql -h /tmp -U postgres -d feedback_bot`, or connects to `127.0.0.1:5432`
- **THEN** the connection fails with `Operation not permitted`

#### Scenario: Database tests in the sandbox
- **WHEN** the sandboxed verification runs the suite
- **THEN** database-backed tests are skipped, and the merge request says database tests have not run yet

#### Scenario: Post-approval full suite passes
- **WHEN** the admin taps ✅ and the approved commit's full suite passes against `feedback_bot_verify_<id>`
- **THEN** the merge proceeds and the throwaway database no longer exists

#### Scenario: Post-approval full suite fails
- **WHEN** any test fails or is skipped in the post-approval run
- **THEN** nothing is merged, the decision is cleared, and the admin receives ⚠️

#### Scenario: Unapproved files excluded
- **WHEN** the workspace contains uncommitted files, or a modified `.venv`
- **THEN** the post-approval run uses only the approved commit and a freshly built venv

### Requirement: Safe token setup
`runner/setup.sh store-token` SHALL:
- read the token from the clipboard and write it to `~/.seb-runner/oauth_token` with mode `0600`
- clear the clipboard
- verify the `sk-ant-oat01-` prefix and a plausible length

It SHALL NOT print the token or accept it as a command-line argument.

#### Scenario: Store token
- **WHEN** the admin copies a token and runs `runner/setup.sh store-token`
- **THEN** the file is created with mode `0600`, the clipboard is cleared, and only the prefix check result and the length are printed

#### Scenario: Clipboard does not hold a token
- **WHEN** the clipboard content does not start with `sk-ant-oat01-`
- **THEN** no file is written and an error is shown

### Requirement: Runner never executes agent-controlled code outside the sandbox
The runner SHALL NOT run tests, scripts or git commands inside a workspace outside the Claude sandbox. It SHALL:
- inspect branches only after fetching them into the main checkout (`refs/runner/<id>`), using the main checkout's configuration
- run verification tests through a sandboxed Claude run, judging them by the raw tool output
- read `.auto/output.json` only if it is a regular, non-symlink file

#### Scenario: Malicious test file
- **WHEN** an agent-written test tries to read `~/.seb-runner/oauth_token` during verification
- **THEN** the read fails inside the sandbox, and the token does not appear in any output

#### Scenario: Malicious git hook
- **WHEN** the workspace contains `.git/hooks/*` or a `core.fsmonitor` setting
- **THEN** no hook or fsmonitor program is executed by the runner, because the runner runs no git commands inside the workspace

#### Scenario: Output file is a symlink
- **WHEN** `.auto/output.json` is a symlink
- **THEN** the runner treats the output as invalid and does not follow the link

#### Scenario: Model misreports tests
- **WHEN** the verification model claims the tests passed, but the raw pytest output shows failures
- **THEN** verification fails

