---
name: planner-fetch-feedback
description: "Fetch the oldest unfinished user feedback and turn it into the planner's next action. Use when: planning next work item, triaging idle backlog, selecting oldest feedback, mapping feedback to OpenSpec context."
argument-hint: "Optional: source=db|backlog|issues, limit=1"
user-invocable: true
---

Find the next actionable feedback item for the planner, grounded in repo evidence.

## Outcome
- Identify whether there is an active OpenSpec change.
- Fetch the oldest unfinished feedback item from the project's source of truth.
- Map that item to the most relevant OpenSpec capability/change.
- Return a concise, decision-oriented next step.

## When To Use
- "Pick the next task from feedback"
- "Find the oldest not-done feedback"
- "What should planner do next?"
- "We're idle; choose the next feedback-driven work item"

## Inputs
- Optional preferred source: `db`, `backlog`, or `issues`
- Optional fetch limit (default `1`)

## Source Priority
1. PostgreSQL feedback tables (`feedback_submissions`, `feedback_events`)
2. In-repo backlog/status files with completion markers
3. External issue tracker if configured

Use the first source that is available and trustworthy in the current workspace.

## Procedure
1. Check planning state in `openspec/`.
2. If an active change exists:
   - Read its `proposal.md`, `design.md`, and `tasks.md`.
   - Return the next step for that change.
   - Stop (do not fetch a new backlog item unless explicitly requested).
3. If no active change exists, fetch the oldest unfinished feedback item.
4. Determine unfinished status by source:
   - DB: if no explicit done flag exists, treat oldest submitted feedback as unfinished and call out this assumption.
   - Backlog files: use explicit done/completed markers.
   - Issues: use open/not-done status.
5. Align the feedback item with relevant OpenSpec context:
   - active or archived changes
   - existing capabilities/specs
   - gaps requiring a new change
6. Return a planner brief with:
   - Current state
   - Oldest unfinished feedback
   - Relevant OpenSpec context
   - Recommended next step
   - Risks/open questions

## PostgreSQL Query Playbook
Use these queries when DB is the selected source.

Oldest submitted feedback (default fallback when no done flag exists):
```sql
SELECT id, user_id, bug_text, suggestion_text, created_at
FROM feedback_submissions
ORDER BY created_at ASC
LIMIT 1;
```

Oldest submitted feedback with lifecycle context:
```sql
SELECT
  s.id,
  s.user_id,
  s.bug_text,
  s.suggestion_text,
  s.created_at,
  COUNT(e.id) FILTER (WHERE e.event_type = 'submitted') AS submitted_events,
  COUNT(e.id) FILTER (WHERE e.event_type = 'cancelled') AS cancelled_events
FROM feedback_submissions s
LEFT JOIN feedback_events e
  ON e.feedback_submission_id = s.id
GROUP BY s.id, s.user_id, s.bug_text, s.suggestion_text, s.created_at
ORDER BY s.created_at ASC
LIMIT 1;
```

Recent queue snapshot (for tie-breaks or manual validation):
```sql
SELECT id, user_id, created_at
FROM feedback_submissions
ORDER BY created_at ASC
LIMIT 10;
```

## Quality Checks
- Use repo evidence; do not invent active changes or feedback records.
- State assumptions explicitly when "unfinished" cannot be directly proven.
- Keep recommendation action-oriented and concise.
- Do not implement code unless user asks.

## Output Format
Current state: ...
Oldest unfinished feedback: ...
Relevant OpenSpec context: ...
Recommended next step: ...
Risks or open questions: ...
