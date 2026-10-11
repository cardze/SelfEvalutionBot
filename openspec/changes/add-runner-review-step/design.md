# Design

## Flow
`do_build` → sandbox tests pass → `do_review` → merge request. `do_review`:

1. `review.reviewers_for(...)` picks the reviewers from the lines the branch adds (the guard's
   `refs.added_lines`, which already skips openspec/ and Markdown): code and security always, plus ux
   and ui when an added line matches `reply_text`, `send_message`, `edit_message_*`, `InlineKeyboard`,
   `ReplyKeyboard` or `parse_mode`. The runner decides this, not an agent.
2. `review.clear` empties `.auto/review/`, then one agent run with `runner/prompts/review.md` (same
   sandbox, settings and limits as BUILD). The top-level `openspec-leader` spawns the named reviewers in
   parallel; each writes `.auto/review/review-<name>.md` with the factory's verdict format. On any
   CHANGES the coder fixes every blocking finding once, runs the tests and commits. `.auto/` is
   gitignored, so the review files are never committed.
3. The branch is fetched again. If its head moved, the fix round committed: the guard is checked again
   (protected path → `fail`, no retry), then the sandbox tests run again (failure → `build_failed`,
   which retries BUILD on the next tick up to `MAX_BUILD_ATTEMPTS`).
4. Verdicts are read by the trusted runner like `output.json`: no symlinks, at most 64 KB, and only
   the first line (`VERDICT: PASS|CHANGES`) decides. CHANGES becomes FIXED when the fix round committed;
   an unreadable file is MISSING; a reviewer not run is SKIPPED. Findings are kept (first 3000 chars).
5. Stored as `auto_runs.review_verdicts` (JSONB), cleared when a new BUILD starts.

An auth failure during REVIEW is handled like one during BUILD. A REVIEW run that fails or times out
does not fail the run: its reviewers show as MISSING and the admin sees that in the 🔀 message.

## Display
- `notify.merge_request(..., review_line)` adds e.g.
  `Review: code ✅ · security 🔧 fixed (ux, ui not run: no bot messages or keyboards changed)` after
  the test line.
- `factory/serve.py` returns the verdicts as the card's `history` (one round), which the dashboard
  already draws as chips, and a `review.md` file with each run reviewer's findings. The dashboard gets
  chip styles for FIXED, MISSING and SKIPPED.

## Affected files
- `runner/review.py` (new), `runner/prompts/review.md` (new), `runner/runner.py`, `runner/refs.py`
  (`head`), `runner/notify.py`
- `storage.py` (`review_verdicts` in the auto_runs whitelist), `sql/init.sql` (column)
- `.claude/agents/review-{code,security,ux,ui}.md` (runner mode), `.claude/agents/openspec-leader.md`
- `factory/serve.py`, `factory/dashboard.html`
- Tests: `tests/test_runner_review_step.py` (new), `tests/test_runner_stages.py`,
  `tests/test_runner_review.py`, `tests/test_factory_serve.py`

## Data model
`ALTER TABLE auto_runs ADD COLUMN IF NOT EXISTS review_verdicts JSONB;`
`{"code": {"verdict": "PASS", "findings": "..."}, "security": {...}, "ux": {...}, "ui": {...}}`
