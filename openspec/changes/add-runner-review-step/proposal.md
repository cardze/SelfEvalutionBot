# Add a review step to the runner

## Problem
A runner-built change reaches the admin's 🔀 merge request with only two checks: the evaluator's
readiness check of the plan (before any code) and the sandboxed test run. Nobody reviews the diff
itself, while /factory jobs get four reviewers (code, security, ux, ui). The admin is the only reviewer
of runner code, from a phone.

## Goals
- After BUILD's tests pass, the factory's reviewers review the diff: `review-code` and
  `review-security` always, `review-ux` and `review-ui` when the diff sends or edits bot messages or
  keyboards.
- Blocking findings get one fix round, after which the tests run again in the sandbox.
- Each reviewer's verdict is shown in the 🔀 merge request and on the dashboard's runner card.

## Non-goals
- A second review round, or blocking the merge request on a reviewer's verdict: the admin decides.
- A new `auto_runs` stage: REVIEW runs inside the BUILD tick, so the stage machine is unchanged.
- Changing the edit permissions (done by `allow-runner-build-edits`).

## Success criteria
- A run with a passing build gets a REVIEW agent run, and `auto_runs.review_verdicts` holds a verdict
  for each of code, security, ux and ui (PASS, CHANGES, FIXED, MISSING or SKIPPED).
- If the fix round commits, the sandbox tests run again; a failure there counts as a failed build
  attempt, and a fix touching a Hermes-protected path fails the run.
- The 🔀 message carries a `Review:` line and the dashboard card shows one round of verdict chips plus
  a `review.md` with the findings.
