## 0. Setup

- [x] 0.1 Create branch `add-autonomous-feedback-runner` off `main` (per AGENTS.md branch rule; this change is built interactively, not by the runner)

## 1. Verify remaining sandbox assumptions (spike, before building on them)

- [x] 1.1 In a scratch local clone outside `/tmp/claude*` and under the D6 settings, confirm the agent can `git add` and `git commit` inside the clone with `GIT_CONFIG_GLOBAL=/dev/null` and `GIT_AUTHOR_*`/`GIT_COMMITTER_*` set
- [x] 1.2 Confirm the agent can create `.venv` and `pip install` a small package with `PIP_CACHE_DIR` inside the clone (PyPI-only network)
- [x] 1.3 Postgres from the sandbox: TCP `localhost:5432` is blocked even with `localhost` allowlisted, and the Unix socket is blocked too. A private Postgres cannot start (`shmget` denied). Local Postgres is `trust` auth, so access must stay blocked → design D10 reworked (C+: no DB in the sandbox, full suite after ✅)
- [x] 1.4 Delete the scratch clone and fixtures

## 2. Bot supervision

- [x] 2.1 Add `runner/launchd/com.seb.bot.plist.template` (`BOT_PYTHON bot.py`, WorkingDirectory, KeepAlive, RunAtLoad, PATH, logs to `~/.seb-runner/logs/bot.{out,err}.log`)
- [x] 2.2 Add `runner/setup.sh` with `install-agents` / `uninstall-agents` (render templates with absolute paths, `launchctl bootstrap`/`bootout gui/$UID`); bot agent first
- [x] 2.3 Manually verify: stop the hand-started bot, install, confirm the bot runs, `kill` it and confirm launchd restarts it, `launchctl kickstart -k` restarts it, logs are written

## 3. Schema and storage

- [x] 3.1 `sql/init.sql`: add `wont_do` to the event-type CHECK list; add the `auto_runs` table and the `uq_auto_runs_single_flight` partial unique index (design D3); run it twice against the local DB
- [x] 3.2 `storage.py`: add `wont_do` to `EVENT_TYPES` (parity test must pass)
- [x] 3.3 `storage.py`: `get_actionable_feedback(user_id=None)`: exclude `wont_do` and in-flight `auto_runs`, optionally filter by submitter
- [x] 3.4 `storage.py`: `auto_runs` access: create (raises on single-flight violation), get in-flight, update stage/change_name/last_error/attempts, set/clear decision and note, set message ids, lookup by `note_prompt_message_id`
- [x] 3.5 `ask.py next --user <id>`
- [x] 3.6 DB-backed tests: `wont_do` exclusion, in-flight exclusion, user filter, single-flight index, decision round-trip

## 4. Bot handlers for runner decisions

- [x] 4.1 `CallbackQueryHandler(pattern=^run:)`: admin-only; ✅ → `decision=merge`, ❌ → `decision=reject`, 💬 → ForceReply prompt + store `note_prompt_message_id`; acknowledge with "Queued; the runner acts within an hour."
- [x] 4.2 Group -1 reply handler: match `(admin, note_prompt_message_id)` → store `decision_note` + `decision=changes`, then `ApplicationHandlerStop`; no match → pass through (coexists with the clarification reply handler)
- [x] 4.3 Handler tests with fakes: non-admin ignored, each button records the right decision, note captured, unrelated reply passes through

## 5. Runner foundation

- [x] 5.1 `runner/config.py`: load `~/.seb-runner/config.env` (MAIN, WORKSPACE_ROOT, BOT_PYTHON, throttle hours, per-stage timeout/budget/max-turns) with the design defaults; load secrets from the main `.env` and the token file
- [x] 5.2 `runner/run.sh`: launchd entrypoint; set PATH; lock via `mkdir ~/.seb-runner/lock` with a pid file and stale-lock detection; exec `runner/runner.py`; log to `~/.seb-runner/logs/runner.log`
- [x] 5.3 `runner/notify.py`: plain-text Telegram senders for 📋, 🔀 (with `run:<id>:m|r|c` buttons), ⚠️ (❌/💬), ✅ merged; store message ids on the run
- [x] 5.4 `runner/settings.template.json` + `setup.sh render-settings` (design D6 with `//` absolute paths)
- [x] 5.5 `setup.sh store-token` (clipboard → `0600` file, clear clipboard, prefix/length check, never prints the token)
- [x] 5.6 ~~`setup.sh test-db`~~ removed by the D10 rework (shared test DB offers no isolation under `trust` auth)
- [x] 5.7 Unit tests: config defaults, settings rendering produces `//` paths, lock stale detection

## 6. Workspace and agent invocation

- [x] 6.1 `runner/workspace.py`: `git clone <MAIN>` to `~/github/SEB-<id8>`, checkout `-b auto/<id8>`, refuse paths under `/tmp/claude*`; create `.venv` with BOT_PYTHON and install requirements; write `.auto/input.json`; remove the workspace
- [x] 6.2 `runner/testdb.py`: post-approval full suite: export the approved ref, fresh venv, throwaway `feedback_bot_verify_<id>`, clean env, verdict, drop (design D10); real DB-backed tests in `tests/test_runner_fullsuite.py`
- [x] 6.3 `runner/snapshot.py`: parse `main:.claude/agents/*.md` frontmatter and body into `--agents` JSON; export `main:.claude/skills/` to `~/.seb-snapshot/.claude/skills/`
- [x] 6.4 `runner/agent.py`: build a clean env (`env -i` equivalent: PATH incl. `.venv/bin`, HOME, LANG, no DB vars, PIP_CACHE_DIR, git identity, `GIT_CONFIG_GLOBAL=/dev/null`, token); run `claude -p` with the design D5 flags under the perl alarm; capture `--output-format json` (cost, errors, auth failure detection)
- [x] 6.5 `runner/prompts/plan.md` and `runner/prompts/build.md`: autonomous-run framing, feedback-as-data warning, `.auto/input.json` contents, required `.auto/output.json` schema, commit requirements
- [x] 6.6 Add an "Autonomous runner mode" section to `.claude/agents/openspec-leader.md` and `planner.md` (and the `.github/agents/` mirrors): when the prompt declares an autonomous runner run, proceed planner → evaluator → coder without waiting for a user, stay within the workspace, and never push
- [x] 6.7 `runner/validate.py`: output.json schema checks + git cross-checks (change folder exists, commits ahead of `main`, dependency list from the `requirements.txt` diff)
- [x] 6.8 Unit tests: agent JSON snapshot parsing, output validation (valid, missing, malformed, dependency mismatch), clean env contains no production secrets

## 7. Self-test

- [x] 7.1 `runner/selftest.py`: canary file in MAIN (gitignored `.auto-canary`), forced Read/Bash-read/token-`wc -c`/outside-write/network checks via a Haiku `stream-json` run under the real settings and env; detect `dangerouslyDisableSandbox`, markers, `sk-ant`; retry an inconclusive check once, then fail closed
- [x] 7.2 `setup.sh selftest` runs it on demand
- [x] 7.3 Parser unit tests on recorded stream-json samples (pass, leak, unsandboxed retry, inconclusive)
- [x] 7.4 Run `setup.sh selftest` for real and confirm it passes; temporarily break a deny rule (single `/`) and confirm it fails

## 7b. Safe inspection and sandboxed verification (design D11)

- [x] 7b.1 `runner/refs.py`: fetch `auto/<id>` into `refs/runner/<id>` in MAIN; commits ahead, diffstat, `requirements.txt` additions, change-folder existence, change-folder export — all via `git -C MAIN`; replace workspace-side git helpers in `validate.py`/`workspace.py`
- [x] 7b.2 `read_output` refuses symlinks and oversized files
- [x] 7b.3 `runner/verify.py`: sandboxed Haiku run executing `.venv/bin/python -m pytest -q tests`; verdict from the raw tool result (summary line + error flag), never the model text
- [x] 7b.4 Tests: fetch-based inspection on temp repos (incl. a workspace with a malicious hook that must not run), symlinked output rejected, verify verdict parsing (pass, failures, no summary, no tool call, model lying)

## 8. Stage machine

- [x] 8.1 `runner/runner.py`: the design D4 sequence (decisions → resume → throttle → pick → PLAN → notify → BUILD → tests → merge request), writing `last_run` only when new work starts
- [x] 8.2 BUILD failure counting (retry next start; `failed` + ⚠️ after 2)
- [x] 8.3 MERGE path per design D8 (clean-main check, re-fetch + sandboxed verification, `merge --no-ff refs/runner/<id>`, archive in MAIN, `resolve_submission`, pip install into BOT_PYTHON, `launchctl kickstart -k`, remove workspace, notify)
- [x] 8.4 REJECT path (`wont_do`, export change folder from `refs/runner/<id>` + `REJECTED.md` into `main`'s archive, commit, remove workspace)
- [x] 8.5 CHANGES path (note → input.json, clear decision, BUILD)
- [x] 8.6 Auth-failure detection → ⚠️ "run `runner/setup.sh store-token`"
- [x] 8.7 Tests for the stage machine with agent/notify/git steps faked: idle start does nothing, throttle respected, decisions processed regardless of throttle, resume from `planned`, failure escalation, each decision path's DB effects

## 9. Runner schedule

- [x] 9.1 `runner/launchd/com.seb.runner.plist.template` (`/bin/bash runner/run.sh`, `StartInterval` 3600, RunAtLoad, PATH, logs); include it in `install-agents`

## 10. Config, rules and docs

- [x] 10.1 `.gitignore`: `.auto/`, `.auto-canary`
- [x] 10.2 AGENTS.md: branch rule allows `auto/<id>` for runner-built changes; describe the runner and that runner branches are merged only via the admin's ✅
- [x] 10.3 README: autonomous runner section (flow diagram, setup steps from the migration plan, costs, how to review a 🔀 branch locally, rollback)
- [x] 10.4 Run the full test suite

## 11. End-to-end

> **Deferred until after merge.** The runner snapshots agents and prompts from `main`, so the first live run can only happen once this change is merged. These tasks are the first live run on `main`, tracked in the conversation, not blocking archive.

- [ ] 11.1 Follow the migration plan: render settings, selftest passes, install agents
- [ ] 11.2 Let the runner pick the open "notice function" submission (answered: "Option 1 and 2"): observe 📋, then 🔀; review the branch locally
- [ ] 11.3 Exercise 💬 once with a small note and observe the rebuilt 🔀
- [ ] 11.4 ✅ Merge and verify: `main` has the change and synced specs, the submission is resolved, the bot restarted with the new code, the workspace is gone
