## Why

Today every step from feedback to shipped feature needs a human to start it: running the planner, proposing, implementing, archiving and merging. The clarification loop made feedback easier to understand, but nothing acts on it unless the admin opens a session. An unattended runner that plans and implements feedback on its own, and stops only for the admin's merge decision, turns the bot into one that "evolves by users' feedback" without that manual work.

Doing this safely needs care. An LLM agent with shell access would run unattended on the admin's Mac, where the bot token, database credentials and SSH keys live. The isolation design in this change was verified by a hands-on test before this proposal was written. That test found that naive settings leak secrets. For example, single-slash deny paths silently match nothing, and the sandbox's unsandboxed-retry escape hatch lets blocked commands succeed.

## What Changes

- **Bot supervision:** `bot.py` runs as a launchd user agent (KeepAlive, file logs). The runner restarts it with `launchctl kickstart -k` after a merge.
- **Runner wrapper** (`runner/`), a trusted shell/Python orchestrator started hourly by a second launchd agent:
  - **Gates:** a lock file, and a 5-hour minimum between new agent work (`last_run`). Pending admin decisions are processed on every hourly run.
  - **Queue:** only the admin's own feedback triggers work, via `ask.py next --user <ADMIN_USER_ID>`. One change is in progress at a time.
  - **Workspace:** one local git clone per change at `~/github/SEB-<id>` on branch `auto/<id>`, with a per-worktree `.venv` and a test database rebuilt each run.
  - **Stages:** a PLAN agent run, then a 📋 notification to the admin (no buttons), then a BUILD agent run, then the full test suite, then a 🔀 merge request with ✅ Merge / ❌ Reject / 💬 Request changes.
  - **After ✅:** merge into `main`, archive the change and sync specs, `resolve_submission`, install dependencies, restart the bot, remove the worktree.
  - **After ❌:** a `wont_do` event, archive with `--skip-specs`, remove the worktree, delete the branch.
  - **After 💬:** the admin's note (via ForceReply) feeds the next BUILD run on the same branch.
- **Agent isolation:**
  - The agent runs with `--setting-sources user`, `--settings <runner settings>`, `--agents <snapshot from main>` and `--agent openspec-leader`.
  - The runner settings are the ones verified in testing: `//` absolute deny paths, sandbox `denyRead`, `allowUnsandboxedCommands: false`, and network access to PyPI only.
  - The agent holds only the test-database credentials. The OAuth token goes to the `claude` process only.
- **Self-test before every agent run:** forced read and write attempts against the token, the main checkout and a path outside the worktree. Any leak or write aborts the run and notifies the admin.
- **Database tests:** the sandbox has no database access (verified). Local Postgres uses `trust` auth, so any access would be a sandbox escape. Database tests therefore skip in the sandbox, and run in full against a throwaway database after ✅, before merging.
- **Schema:**
  - New `auto_runs` table recording stage, admin decision and note per submission.
  - New `wont_do` event type (EVENT_TYPES, CHECK constraint, parity test).
- **Setup helper:** `runner-setup.sh store-token` saves the OAuth token from the clipboard with `0600` permissions. It exists so the token is never typed on a command line; a real leak during exploration showed why.
- **Rules:** the AGENTS.md branch rule allows `auto/<id>` branches for automated runs. `.auto/` is added to `.gitignore`.

## Capabilities

### New Capabilities
- `bot-supervision`: Running the bot under launchd with automatic restart, logs, and a restart command the runner can call.
- `autonomous-feedback-runner`: The runner's schedule, gates, stage machine (plan, notify, build, merge request), admin decisions (merge, reject, request changes), worktree lifecycle and post-merge steps.
- `runner-isolation`: Secret handling, agent sandbox and permission settings, the agent-definition snapshot, database-test strategy, and the self-test that runs before every agent run.

### Modified Capabilities
- `feedback-event-integrity`: The allowed event types gain `wont_do`.
- `planner-feedback-triage`: The actionable queue excludes `wont_do` submissions and supports filtering by submitter (`ask.py next --user`).

## Impact

- **New files:**
  - `runner/` (wrapper, stage scripts, settings template, self-test, setup helper)
  - launchd plist templates for the bot and the runner
- **Code:**
  - `storage.py`: `auto_runs` access, `wont_do`, a user filter on the queue
  - `ask.py`: `next --user`
  - `bot.py`: callback and ForceReply handlers for the 🔀 buttons
- **Schema:** `sql/init.sql` gets the `auto_runs` table and `wont_do` in the CHECK constraint.
- **Local system setup (manual, documented):**
  - launchd agents in `~/Library/LaunchAgents/`
  - `~/.seb-runner/` holding the token, logs, lock and `last_run`
- **Dependencies:** no new Python packages. It requires Claude Code (verified with 2.1.210) and the macOS system `perl` for timeouts.
- **Cost:**
  - Hourly runs with nothing to do cost nothing, because no Claude session starts.
  - A real run costs one self-test (about $0.05) plus the PLAN and BUILD runs, each capped by `--max-budget-usd`.
- **Out of scope:**
  - Feedback from users other than the admin
  - Parallel changes
  - Cloud execution
  - A migration dry run against a copy of real data (possible later addition)
  - "Your feature shipped" notices to other submitters
