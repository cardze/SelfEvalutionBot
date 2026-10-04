## MODIFIED Requirements

### Requirement: Stage progression within a run
For a new submission, the runner SHALL:
1. create a workspace
2. run a PLAN agent run and notify the admin (📋) with the plan summary and its impact — the changes (commands and files affected), the risk (what could break) and the size (small, medium or large); PLAN output without a valid impact SHALL fail the stage
3. if the submission was created from an accepted runner signal, stop and wait for the admin's ▶️ Build or ❌ Drop on the 📋 message; otherwise continue
4. run a BUILD agent run
5. fetch the branch into the main checkout and run the test suite inside the sandbox (database tests skip there)
6. if the suite passes, send a merge request (🔀) with ✅ Merge, ❌ Reject and 💬 Request changes

It SHALL continue through these stages in one start, stopping only when waiting for a decision or on failure.

#### Scenario: Straight-through run
- **WHEN** a new admin submission that did not come from a runner signal is picked, and PLAN, BUILD and the tests all succeed
- **THEN** within one runner start the admin receives the 📋 notification with its impact and then the 🔀 merge request, and the run's stage is `awaiting_decision`

#### Scenario: Runner-suggested work waits for build approval
- **WHEN** a submission created from an accepted signal is picked and PLAN succeeds
- **THEN** the run stops in stage `planned`, no BUILD agent runs, and the 📋 message offers ▶️ Build and ❌ Drop

#### Scenario: Build approved
- **WHEN** a gated run in stage `planned` has `decision='build'`
- **THEN** the next runner start clears the decision and runs BUILD

#### Scenario: Dropped at plan
- **WHEN** a gated run in stage `planned` has `decision='reject'`
- **THEN** the reject path runs: a `wont_do` event is recorded and the proposal is archived with `REJECTED.md`

#### Scenario: Invalid impact
- **WHEN** PLAN output has no `impact`, or its `size` is not small, medium or large
- **THEN** the PLAN stage fails

#### Scenario: Resume after crash
- **WHEN** a runner start finds a run in stage `planned` or `building`
- **THEN** it resumes with BUILD, without re-planning, unless the run is gated and has no `build` decision, in which case it keeps waiting

### Requirement: Admin decisions via Telegram
The bot SHALL accept ✅, ❌, 💬 and ▶️ taps on runner messages only from `ADMIN_USER_ID`, and SHALL record them on the matching `auto_runs` row. ▶️ Build SHALL be accepted only for a run in stage `planned`, and ❌ additionally for a run in stage `planned`. 💬 SHALL prompt for a note via ForceReply, and the reply SHALL be stored as `decision_note`. The bot SHALL NOT merge, reject, build or run agents itself.

#### Scenario: Non-admin tap
- **WHEN** a user other than the admin triggers a runner callback
- **THEN** it is ignored and the run is unchanged

#### Scenario: Merge tapped
- **WHEN** the admin taps ✅ Merge
- **THEN** `decision='merge'` is stored, and the admin is told the runner will act within an hour

#### Scenario: Build tapped
- **WHEN** the admin taps ▶️ Build on a 📋 message for a run in stage `planned`
- **THEN** `decision='build'` is stored, and the admin is told the build starts within an hour

#### Scenario: Request changes
- **WHEN** the admin taps 💬 and replies to the prompt with a note
- **THEN** `decision='changes'` and `decision_note` are stored, and the reply is not processed by other conversations
