---
name: planner-fetch-feedback
description: "Fetch the next actionable user feedback, ask the submitter one clarifying question when it is ambiguous, and turn it into the planner's next action. Use when: planning next work item, triaging idle backlog, selecting feedback, mapping feedback to OpenSpec context."
argument-hint: "Optional: submission id to focus on"
user-invocable: true
---

Find the next actionable feedback item for the planner, grounded in repo evidence. Clarify it with the submitter if different readings would lead to different work.

## Outcome
- Identify whether there is an active OpenSpec change.
- Fetch the next actionable feedback item via `ask.py next`.
- Decide whether the item is clear enough to plan or needs one clarifying question.
- Map the item to the most relevant OpenSpec capability or change.
- Return a concise, decision-oriented planner brief.

## When To Use
- "Pick the next task from feedback"
- "What should planner do next?"
- "We're idle; choose the next feedback-driven work item"

## Source of truth
Use **only** `python ask.py next` to read the feedback queue. Do not query the feedback tables with raw SQL. The definition of "actionable" lives in `FeedbackService.get_actionable_feedback()`:
- resolved submissions (a `resolved` event) are excluded
- submissions waiting on the admin (`pending_approval`) or on the submitter (`sent`) are excluded and only counted
- answered clarifications come first, then everything else oldest-first

`ask.py next` prints JSON:
```json
{
  "actionable": [
    {"id": "...", "user_id": 123, "bug_text": "...", "suggestion_text": "...", "created_at": "...",
     "clarification_status": null | "answered" | "discarded",
     "clarification_question": "...", "clarification_options": ["..."],
     "clarification_answer": "...", "clarification_answer_source": "option" | "free_text"}
  ],
  "pending_approval": 0,
  "parked": 0
}
```

## Procedure
1. **Active change check.** Run `openspec list --json`. If a change is active, read its `proposal.md`, `design.md` and `tasks.md`, return its next step, and stop.
2. **Fetch.** Run `python ask.py next`. If `actionable` is empty, report that, including the `pending_approval` and `parked` counts, and stop.
3. **Take the first actionable item** and branch on `clarification_status`:
   - `answered`: use `clarification_answer` as the user's intent. Treat the item as fresh. Check it against the **current** OpenSpec specs and code, not the state when the question was asked. Go to step 5.
   - `discarded`: the admin chose not to ask. Proceed with your best interpretation and record it as an explicit assumption. Go to step 5.
   - `null`: go to step 4.
4. **Ambiguity gate.** Ask yourself: *would different reasonable readings of this feedback lead to different features or fixes?*
   - **No:** go to step 5.
   - **Yes:** draft one clarifying question (see "Writing a clarification") and run:
     ```bash
     python ask.py draft <submission_id> --question "…" --option "…" --option "…" [--option "…"]
     ```
     This stores the draft and sends a preview to the admin in Telegram for ✅/❌ approval. Do **not** pass `--yes` unless the user explicitly tells you to. Report the item as "awaiting approval", then **go back to step 3 with the next actionable item**. One question waiting must not block the queue.
     - If `ask.py` exits non-zero, report the error verbatim and do not retry with a different draft. Each submission gets exactly one clarification.
5. **Align with OpenSpec context:** active or archived changes, existing capabilities in `openspec/specs/`, and gaps that need a new change.
6. **Return the planner brief** (see Output Format).

## Writing a clarification
You get **one** question per submission, so spend it well.
- **Only ask when the answer changes what gets built.** If all readings lead to the same work, don't ask.
- **Quote the submitter's own words** so they recognise their request, e.g. `About your idea "I want to have a notice function": what did you mean?`
- **2–4 mutually exclusive options**, each leading to different work. At most 30 characters each. The bot adds "✏️ Something else" automatically, so do not add your own "other" option.
- **Plain, non-technical language.** "Remind me at a time I set", not "scheduled job".
- **Same language as the original feedback.** If they wrote in Chinese, ask in Chinese.
- Question at most 500 characters, plain text (no Markdown).

## Quality Checks
- Use repo evidence. Do not invent active changes or feedback records.
- State assumptions explicitly, especially for `discarded` clarifications.
- Keep the recommendation action-oriented and concise.
- Do not implement code unless the user asks.

## Output Format
Current state: ...
Next actionable feedback: <id> — "<bug_text>" / "<suggestion_text>" (<created_at>)
Clarification: none | drafted, awaiting approval | answered: "<answer>" (<option|free_text>) | discarded (assumption: ...)
Queue: <n> actionable, <pending_approval> awaiting admin approval, <parked> waiting on users
Relevant OpenSpec context: ...
Recommended next step: ...
Risks or open questions: ...
