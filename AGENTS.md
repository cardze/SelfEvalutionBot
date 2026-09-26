# Agent Guidelines

This file is the authoritative reference for how AI agents must behave in this repository.
Read it before taking any action on the codebase.

---

## OpenSpec-first rule

**Every feature, fix, or schema change must be backed by an OpenSpec change before code is written.**

This is non-negotiable. Code written without a corresponding OpenSpec change is out of process
and must be retroactively documented before it is merged.

### What counts as a change that requires OpenSpec

- New database columns, tables, or event types
- New public methods on service classes (`storage.py`, `db.py`, etc.)
- New bot commands or changes to existing command behavior
- New dependencies added to `requirements.txt`
- Any change to `sql/init.sql`

### What does NOT require OpenSpec

- Fixing a typo in a log message
- Adding or updating a test that covers already-documented behavior
- Updating comments or docstrings

---

## OpenSpec workflow

Use the agents in `.claude/agents/` in this order:

```
openspec-leader  →  planner  →  evaluator  →  coder
```

1. **openspec-leader** — starts every non-trivial task; explores repo state and decides what comes next.
2. **planner** — picks the next work item from feedback or backlog when no active change exists.
3. **evaluator** — reviews the plan, identifies gaps, and generates a test plan before implementation.
4. **coder** — writes code only after a proposal, design, and tasks file exist under `openspec/changes/<name>/`.

Never call `coder` directly without a backed change. If the evaluator has not approved, do not proceed.

### Branch rule (non-negotiable)

**Create a dedicated branch before writing any code.** Branch off `main` using the change name:

```
git checkout main
git checkout -b <change-name>   # e.g. add-calculator
```

- One branch per OpenSpec change.
- Never implement directly on `main`.
- Merge back to `main` only after all tasks are checked and tests pass.
- If you find yourself on `main` when implementation starts, stop and create the branch first.

**Exception: runner-built changes.** The autonomous feedback runner (`runner/`) builds changes in its own
workspace clone on a branch named `auto/<submission-id-prefix>`; the OpenSpec change name is still chosen
by the agent. Runner branches are merged into `main` **only** by the runner after the admin taps ✅ Merge
in Telegram — never merge or push an `auto/*` branch by hand or from an agent.

---

## Autonomous feedback runner

`runner/` turns the admin's own feedback into OpenSpec changes without a human starting anything:
launchd starts `runner/run.sh` hourly → PLAN agent run → 📋 notice → BUILD agent run → sandboxed test
verification → 🔀 merge request (✅ Merge / ❌ Reject / 💬 Request changes).

- Agents in a runner run are sandboxed (`runner/settings.template.json`) and must never try to reach
  secrets, the main checkout, or the network beyond PyPI. A self-test verifies this before every run.
- The trusted runner never executes agent-written code or git config outside the sandbox (design D11
  of the `add-autonomous-feedback-runner` change).
- When an agent prompt begins with `AUTONOMOUS RUNNER RUN`, follow the "Autonomous runner mode"
  section of `openspec-leader` / `planner`.

### Reviewing runner changes

With every 🔀 merge request the runner points a local branch `review/<change-name>` in the main
checkout at the exact commit under review. Review it **by diff only**:

```
git diff main...review/<change-name>
git show review/<change-name>:path/to/file
```

- **Never check out a `review/*` branch in the main checkout.** launchd runs the bot and the runner
  from the main checkout's working tree, so a checkout hands agent-written code the OAuth token, the
  Telegram token and the database on the next hourly run or bot restart.
- Never run git, tests, `.venv` binaries, an editor or Claude Code inside a `SEB-*` workspace or in a
  worktree of a `review/*` branch. Their `.git/config`, `conftest.py`, `.claude/settings.json`,
  `.vscode/` and `.envrc` are agent-controlled and would run outside the sandbox. This applies to
  reviewing agents as well as people.
- Read the ⚠️ sensitive-paths list in the 🔀 message closely: it flags edits to `runner/`,
  `.claude/`, `.github/`, `AGENTS.md`, test and packaging config, and `requirements.txt`.
- The `review/` namespace belongs to the runner: it overwrites and deletes those branches. Never
  push them (avoid `git push --all` / `--mirror`).

---

## OpenSpec change structure

Each change lives at `openspec/changes/<name>/` and must contain:

| File | Purpose |
|------|---------|
| `proposal.md` | Problem, goals, non-goals, success criteria |
| `design.md` | Technical approach, affected files, data model |
| `specs/<capability>/spec.md` | Behavioral spec for each new or changed capability |
| `tasks.md` | Checklist of implementation tasks; each item is checked off as it completes |

A change is complete when all tasks are checked and the evaluator signs off.
Archive it by moving the directory into `openspec/changes/archive/YYYY-MM-DD-<name>/`
and adding a `.openspec.yaml` summary file.

---

## Feedback resolution

The `feedback_events` table uses event sourcing. A submission is considered **resolved** when a
row with `event_type = 'resolved'` exists for it in `feedback_events`.

- Use `FeedbackService.resolve_submission(submission_id)` to resolve a submission.
- Use `FeedbackService.get_unresolved_feedback(limit=N)` to fetch the oldest unresolved items.
- Never add a `resolved_at` column to `feedback_submissions`; the events table is the source of truth.

This pattern was chosen over a column flag so the full event timeline is preserved.
See the `feedback-persistence` archived change for the original schema rationale.

---

## Known out-of-process changes

None currently. (The `resolved` event type and `resolve_submission` / `get_unresolved_feedback`
are now documented by the `feedback-event-integrity` spec from the `add-feedback-clarification` change.)
