## MODIFIED Requirements

### Requirement: No database access from the sandbox
Agent runs and sandboxed verifications SHALL have no database access: no `POSTGRES_*` settings, and Postgres unreachable over both TCP and the Unix socket. Database-backed tests SHALL run only in the post-approval full-suite run, after the admin taps ✅, against a throwaway database created and dropped by the runner, on the tree that merging the approved commit into `main` produces, in a fresh venv, and with an environment that holds no bot token.

#### Scenario: Agent tries the production database
- **WHEN** the agent runs `psql -h /tmp -U postgres -d feedback_bot`, or connects to `127.0.0.1:5432`
- **THEN** the connection fails with `Operation not permitted`

#### Scenario: Database tests in the sandbox
- **WHEN** the sandboxed verification runs the suite
- **THEN** database-backed tests are skipped, and the merge request says database tests have not run yet

#### Scenario: Post-approval full suite passes
- **WHEN** the admin taps ✅ and the merged tree's full suite passes against `feedback_bot_verify_<id>`
- **THEN** the merge proceeds and the throwaway database no longer exists

#### Scenario: Post-approval full suite fails
- **WHEN** any test fails or is skipped in the post-approval run
- **THEN** nothing is merged, the decision is cleared, and the admin receives ⚠️

#### Scenario: Change conflicts with main
- **WHEN** the approved commit cannot be merged into `main` without conflicts
- **THEN** no suite runs, nothing is merged, and the admin receives ⚠️ saying it conflicts with main

#### Scenario: Unapproved files excluded
- **WHEN** the workspace contains uncommitted files, or a modified `.venv`
- **THEN** the post-approval run uses only the approved commit, `main` and a freshly built venv
