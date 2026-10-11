## ADDED Requirements

### Requirement: Reviewers review every runner build before the merge request
After BUILD's sandboxed tests pass, the runner SHALL run `review-code` and `review-security` on the
branch's diff, and additionally `review-ux` and `review-ui` when a line the branch adds sends or edits a
bot message or keyboard. Blocking findings SHALL get exactly one fix round; when that round commits,
the runner SHALL check the protected paths and run the sandboxed tests again before the merge request.

#### Scenario: All reviewers pass
- **WHEN** BUILD's tests pass and every reviewer writes `VERDICT: PASS`
- **THEN** the branch is unchanged and the 🔀 merge request is sent with each verdict

#### Scenario: A blocking finding is fixed
- **WHEN** a reviewer writes `VERDICT: CHANGES` and the fix round commits
- **THEN** the sandbox tests run again, and that reviewer's verdict is shown as fixed

#### Scenario: Tests fail after the fix round
- **WHEN** the sandbox tests fail after the fix round
- **THEN** the build attempt counts as failed and is retried on the next tick, up to the attempt limit

#### Scenario: The fix touches a protected path
- **WHEN** the fix round commits a change to a Hermes-protected path
- **THEN** the run fails without a retry and the admin is told why

#### Scenario: No bot messages changed
- **WHEN** no added line sends or edits a bot message or keyboard
- **THEN** only code and security review, and ux and ui are shown as not run

### Requirement: Review verdicts are shown to the admin
The runner SHALL store each reviewer's verdict (PASS, CHANGES, FIXED, MISSING or SKIPPED) and findings
on the run, read only from the first line of a regular, size-limited, non-symlinked file. The 🔀
merge request SHALL include a `Review:` line, and the dashboard's runner card SHALL show the verdicts as
one round of chips with the findings in `review.md`.

#### Scenario: A reviewer writes no verdict
- **WHEN** a reviewer's file is missing, garbled, oversized or a symlink
- **THEN** its verdict is MISSING and the merge request says it gave no verdict

#### Scenario: A new build starts
- **WHEN** BUILD runs again (retry or 💬 Request changes)
- **THEN** the previous verdicts are cleared until the new review finishes
