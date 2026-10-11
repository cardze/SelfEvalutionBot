## 1. Runner

- [x] 1.1 `runner/review.py`: choose reviewers, clear and read verdicts safely, merge-request line
- [x] 1.2 `runner/prompts/review.md`: REVIEW prompt (parallel reviewers, one fix round, tests, commit)
- [x] 1.3 `do_review` in `runner/runner.py` after BUILD's tests pass: re-fetch, guard and re-test on a fix
- [x] 1.4 `refs.head`; `notify.merge_request` review line
- [x] 1.5 `auto_runs.review_verdicts` column, storage whitelist; cleared when BUILD starts

## 2. Agents

- [x] 2.1 Runner mode note in `review-code`, `review-security`, `review-ux`, `review-ui`
- [x] 2.2 `openspec-leader` autonomous mode mentions the REVIEW stage

## 3. Dashboard

- [x] 3.1 `factory/serve.py`: verdicts as a round of chips and `review.md`
- [x] 3.2 `factory/dashboard.html`: chip styles for FIXED, MISSING, SKIPPED; demo card

## 4. Tests

- [x] 4.1 `tests/test_runner_review_step.py`: reviewer choice, verdict reading, summary line
- [x] 4.2 Stage tests: pass, fixed and re-tested, unfixed, tests failing after fix, protected fix
- [x] 4.3 Merge-request line and dashboard card tests
