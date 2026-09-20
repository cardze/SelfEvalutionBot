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

The following were implemented without a prior OpenSpec change and should be documented
in a follow-up change before the branch is merged:

| Change | Files affected | Status |
|--------|---------------|--------|
| Add `resolved` event type and `resolve_submission` / `get_unresolved_feedback` to `FeedbackService` | `storage.py`, `sql/init.sql` | needs OpenSpec change |
