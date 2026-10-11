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
- **D7 Verdict lines.** Reviews start with `VERDICT: PASS|CHANGES`; `decision.md` starts with
  `APPROVE|ESCALATE`. The orchestrator and the dashboard parse only that first line.
