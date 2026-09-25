# autonomous-feedback-runner Specification

## Purpose
Define how the hourly runner turns the admin's feedback into OpenSpec changes: schedule and throttling, the single in-flight run, the PLAN/BUILD stages, admin decisions in Telegram, and the merge, reject and request-changes paths.
## Requirements
### Requirement: Hourly schedule with throttled new work
The runner SHALL be started hourly by launchd, and also at load. It SHALL process pending admin decisions and resume in-flight runs on every start. It SHALL start work on a new submission only if at least 5 hours have passed since new work last started.

#### Scenario: Decision processed promptly
- **WHEN** the admin taps ✅ Merge, and the next hourly start is less than 5 hours after the last new work
- **THEN** that start performs the merge

#### Scenario: New work throttled
- **WHEN** an hourly start finds actionable feedback, but new work started less than 5 hours ago
- **THEN** the runner exits without starting an agent

#### Scenario: Idle start costs nothing
- **WHEN** there is no in-flight run, no pending decision, and no actionable admin feedback
- **THEN** the runner exits without starting any Claude session

### Requirement: Single run at a time
The runner SHALL hold an exclusive lock while running. At most one `auto_runs` row SHALL be in flight (stage not `merged` or `rejected`), enforced by a partial unique index.

#### Scenario: Overlapping start
- **WHEN** the runner starts while a previous start still holds the lock
- **THEN** the new start exits immediately

#### Scenario: Stale lock
- **WHEN** the lock exists but its recorded process is no longer alive
- **THEN** the runner removes the stale lock and proceeds

#### Scenario: Second in-flight run rejected
- **WHEN** an attempt is made to create a run while another is in flight
- **THEN** the database rejects the insert

### Requirement: Only admin feedback triggers runs
The runner SHALL select new work only from `ask.py next --user <ADMIN_USER_ID>`.

#### Scenario: Other user's feedback
- **WHEN** the only actionable submission is from a user other than the admin
- **THEN** the runner starts no work, and the submission stays in the queue for manual planning

### Requirement: Stage progression within a run
For a new submission, the runner SHALL:
1. create a workspace
2. run a PLAN agent run and notify the admin (📋, no buttons)
3. run a BUILD agent run
4. fetch the branch into the main checkout and run the test suite inside the sandbox (database tests skip there)
5. if the suite passes, send a merge request (🔀) with ✅ Merge, ❌ Reject and 💬 Request changes

It SHALL continue through these stages in one start, stopping only when waiting for a decision or on failure.

#### Scenario: Straight-through run
- **WHEN** a new admin submission is picked, and PLAN, BUILD and the tests all succeed
- **THEN** within one runner start the admin receives the 📋 notification and then the 🔀 merge request, and the run's stage is `awaiting_decision`

#### Scenario: Resume after crash
- **WHEN** a runner start finds a run in stage `planned` or `building`
- **THEN** it resumes with BUILD, without re-planning

### Requirement: Output validation
The runner SHALL validate the agent's `.auto/output.json` against the stage's schema, and SHALL cross-check it against the workspace's git state. Any mismatch SHALL be treated as a failed stage.
- After PLAN, `openspec/changes/<change_name>/` must exist.
- After BUILD, the branch must have commits beyond `main`.
- New dependencies SHALL be taken from the `requirements.txt` diff, not from what the agent reports.

#### Scenario: Missing output file
- **WHEN** an agent run ends without writing a valid `.auto/output.json`
- **THEN** the stage is marked failed and counted as a failed attempt

#### Scenario: Dependency mismatch
- **WHEN** the agent reports no new dependencies, but `requirements.txt` changed
- **THEN** the merge request lists the dependencies from the diff

### Requirement: Build failure handling
A BUILD whose agent run fails, or whose test suite fails, SHALL be retried on the next start. After 2 failed attempts, the run SHALL move to `failed`, and the admin SHALL receive a ⚠️ message with ❌ Reject and 💬 Retry with note.

#### Scenario: Second failure
- **WHEN** BUILD fails for the second time
- **THEN** the stage becomes `failed` and the admin receives the ⚠️ message

### Requirement: Admin decisions via Telegram
The bot SHALL accept ✅, ❌ and 💬 taps on runner messages only from `ADMIN_USER_ID`, and SHALL record them on the matching `auto_runs` row. 💬 SHALL prompt for a note via ForceReply, and the reply SHALL be stored as `decision_note`. The bot SHALL NOT merge, reject or run agents itself.

#### Scenario: Non-admin tap
- **WHEN** a user other than the admin triggers a runner callback
- **THEN** it is ignored and the run is unchanged

#### Scenario: Merge tapped
- **WHEN** the admin taps ✅ Merge
- **THEN** `decision='merge'` is stored, and the admin is told the runner will act within an hour

#### Scenario: Request changes
- **WHEN** the admin taps 💬 and replies to the prompt with a note
- **THEN** `decision='changes'` and `decision_note` are stored, and the reply is not processed by other conversations

### Requirement: Merge path
On `decision='merge'` the runner SHALL:
1. require a clean main checkout on `main`
2. re-fetch the branch and run the complete test suite, including database tests, against a throwaway database
3. merge the fetched branch into `main` with `--no-ff`
4. archive the change with spec sync in the main checkout, and commit
5. resolve the submission
6. install `requirements.txt` into the bot's Python
7. restart the bot
8. remove the workspace
9. set stage `merged`
10. notify the admin

#### Scenario: Successful merge
- **WHEN** a merge decision is processed and all steps succeed
- **THEN** `main` contains the change and its synced specs, the submission has a `resolved` event, the bot is restarted, and the workspace directory no longer exists

#### Scenario: Dirty main checkout
- **WHEN** a merge decision is processed while the main checkout has uncommitted changes
- **THEN** nothing is merged, the admin receives ⚠️, and the merge is retried on the next start

#### Scenario: Tests fail at merge time
- **WHEN** the test suite fails during the merge path
- **THEN** nothing is merged, the decision is cleared, and the admin receives ⚠️

### Requirement: Reject path
On `decision='reject'` the runner SHALL:
1. record a `wont_do` event for the submission
2. copy the change's OpenSpec folder into `openspec/changes/archive/<date>-<change>/` on `main`, with `REJECTED.md` containing the admin's note if any, without syncing specs
3. commit that on `main`
4. remove the workspace
5. set stage `rejected`

#### Scenario: Rejected feature
- **WHEN** a reject decision is processed
- **THEN** the submission never appears in the actionable queue again, `openspec/specs/` is unchanged, and the workspace no longer exists

### Requirement: Changes path
On `decision='changes'` the runner SHALL:
1. pass `decision_note` to the next BUILD via `.auto/input.json`
2. clear the decision
3. run BUILD again on the same branch

#### Scenario: Revision
- **WHEN** the admin requests changes with the note "use relative times only"
- **THEN** the next BUILD agent run receives that note, and a new 🔀 merge request follows

### Requirement: Workspace per change
Each run SHALL use its own local git clone of the main checkout at `~/github/SEB-<id-prefix>`, on branch `auto/<id-prefix>`, with a per-workspace `.venv`. The workspace SHALL NOT be a `git worktree` of the main checkout, and SHALL NOT be located under `/tmp/claude*`. It SHALL be removed when the run is merged or rejected.

#### Scenario: Agent cannot change main's refs
- **WHEN** the agent commits or manipulates refs inside its workspace
- **THEN** the main checkout's branches are unaffected until the runner merges

#### Scenario: Cleanup
- **WHEN** a run reaches `merged` or `rejected`
- **THEN** its workspace directory has been deleted

