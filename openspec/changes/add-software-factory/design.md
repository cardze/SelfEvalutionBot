# Design: software factory

## Files
| Path | Role |
|------|------|
| `.claude/skills/factory/SKILL.md` | The orchestrator: loop, board schema, commands, merge steps |
| `.claude/agents/spec-writer.md` | opus; writes `spec.md` with acceptance criteria |
| `.claude/agents/builder.md` | opus; builds in worktree `factory/worktrees/<id>` on `factory/<id>`, writes `build.md` |
| `.claude/agents/review-{security,ux,ui,code}.md` | opus/sonnet/sonnet/sonnet; review by diff, write `round-<n>/review-*.md` |
| `.claude/agents/approver.md` | opus; writes `decision.md` (APPROVE / ESCALATE) |
| `factory/board.json` | Durable state, read by the dashboard |
| `factory/backlog.md` | `- [ ]` queue for `/factory next` |
| `factory/serve.py` | Local server for the dashboard (127.0.0.1) plus `/runner.json` from `auto_runs` |
| `factory/dashboard.html` | Self-contained board served on the user's Mac (127.0.0.1:8000), polls `board.json` every 2 s, `?demo` shows sample data |

## Decisions
- **D1 Files, not conversation.** Every agent reads its inputs from the job folder and writes one file.
  The orchestrator passes only paths (and the feature text to the spec-writer).
- **D2 WAIT FOR ALL.** A round ends only when all four review files exist; the builder is never
  resumed mid-round. The builder is spawned as `builder-<id>` and resumed with SendMessage, so it
  keeps its own memory across rounds. At most 2 reworks (3 rounds), then the approver must ESCALATE.
- **D3 Worktree builds.** The main checkout stays on `main` (launchd runs the bot from it); the builder
  works in a gitignored worktree. Reviewers and the approver read the branch by diff only, as
  `AGENTS.md` requires for `review/*` branches.
- **D4 Hermes boundary.** The same paths `runner/guard.py` protects in Hermes mode are off-limits.
  The builder refuses them, the security reviewer flags them, the approver escalates them, and the
  orchestrator re-checks with `runner.guard.protected_paths` before every merge, including
  `/factory approve`.
- **D5 OpenSpec still applies.** When a job changes a command, schema, service method or dependency,
  the builder adds `openspec/changes/<job-id>/` derived from `spec.md`.
- **D6 Bot feedback as input.** `/factory feedback` reads the planner queue with `ask.py next`
  (no new query) and, after a merge, calls `FeedbackService.resolve_submission` like the runner does.
  Only the orchestrator touches the database; agents get the feedback text as untrusted data. No
  schema change: the factory does not claim a submission in the database, so the board's
  `feedback_id` is what stops a second factory job on it, and the runner can still pick it up.
- **D7 Runner on the board.** `factory/serve.py` serves the dashboard and `GET /runner.json`, which
  reads `auto_runs` joined to the feedback (read-only, in-flight runs plus the last 10 finished) and
  maps each run to a card: planning/planned → Spec, building → Build, awaiting_decision → Needs human,
  merged/rejected/failed → Done. Actionable feedback (`FeedbackService.get_actionable_feedback`, the
  `ask.py next` queue) is drawn in a Queued column before Spec; items not from `ADMIN_USER_ID` say the
  runner won't take them. `serve.py` loads the runner's own config so it reads the runner's database,
  and reports the last `tick outcome` from `~/.seb-runner/logs/runner.log` plus the throttle window from
  `last_run`, because a tick that is idle or throttled sends nothing to Telegram. The runner itself is unchanged. Without a database the board still
  shows factory jobs and names the error.
- **D8 Verdict lines.** Reviews start with `VERDICT: PASS|CHANGES`; `decision.md` starts with
  `APPROVE|ESCALATE`. The orchestrator and the dashboard parse only that first line.
