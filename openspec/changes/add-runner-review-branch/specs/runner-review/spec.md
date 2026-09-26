## ADDED Requirements

### Requirement: Review branch for each merge request
When the runner sends a 🔀 merge request, it SHALL point the local branch
`refs/heads/review/<change-name>` in the main checkout at exactly the commit the merge request
describes (the commit of `refs/runner/<id>`). It SHALL write the branch with `git update-ref`
under the main checkout's configuration and the runner's defensive git flags, and SHALL NOT run
any git command inside the workspace to do so.

#### Scenario: Branch appears with the merge request
- **WHEN** BUILD and sandboxed verification pass and the 🔀 message is sent for change `add-meal-picker`
- **THEN** `git -C <MAIN> rev-parse review/add-meal-picker` equals `git -C <MAIN> rev-parse refs/runner/<id>`

#### Scenario: Stale branch is overwritten
- **WHEN** a `review/<change-name>` branch already exists pointing at an unrelated commit and a new 🔀 is sent for that change
- **THEN** the branch is moved to the newly reviewed commit

#### Scenario: No branch before review
- **WHEN** a run has finished PLAN but BUILD has not yet passed verification
- **THEN** no `review/<change-name>` branch exists for it

### Requirement: Review branch lifecycle
The runner SHALL delete `review/<change-name>` when BUILD starts again for the run, when the run
is merged, and when the run is rejected (including when the main checkout is not on `main`, and
doing nothing when the run has no change name). It SHALL keep the branch when a merge is aborted.
It SHALL set the branch before marking the run `awaiting_decision`. If the review branch is checked
out in any worktree of the main checkout, the runner SHALL NOT move or delete it and SHALL send the
admin a ⚠️ warning instead.

#### Scenario: Request changes
- **WHEN** the admin requests changes and the next BUILD starts
- **THEN** the review branch no longer exists until the next 🔀 is sent

#### Scenario: Merged
- **WHEN** the merge path completes successfully
- **THEN** neither `review/<change-name>` nor `refs/runner/<id>` exists in the main checkout

#### Scenario: Rejected
- **WHEN** the reject path completes
- **THEN** `review/<change-name>` no longer exists

#### Scenario: Reject a run whose PLAN failed
- **WHEN** a run with no change name is rejected
- **THEN** the reject path completes without error

#### Scenario: Merge aborted
- **WHEN** the full test suite fails during the merge path
- **THEN** `review/<change-name>` still points at the reviewed commit

#### Scenario: Review branch is checked out
- **WHEN** the runner would move or delete `review/<change-name>` while that branch is checked out in the main checkout or in a linked worktree of it
- **THEN** the branch is left unchanged and the admin receives a ⚠️ warning naming the branch

### Requirement: Sensitive-path warning in the merge request
The 🔀 message SHALL list, under a ⚠️ heading, the changed files (computed in the main checkout,
NUL-separated so no path is quoted, with renames disabled so both sides of a move are included)
that — compared case-insensitively — start with `runner/`, `.claude/`, `.github/` or `.vscode/`;
equal `AGENTS.md`, `CLAUDE.md`, `.envrc`, `requirements.txt`, `sql/init.sql`, `pytest.ini`,
`pyproject.toml`, `setup.cfg`, `tox.ini`, `.gitattributes` or `.gitmodules`; or have basename
`conftest.py`. The list SHALL be capped at 15 paths with
a count of the remainder. When no such file changed, the section SHALL be omitted. The warning
SHALL NOT change the message's buttons or the merge decision flow.

#### Scenario: Runner code touched
- **WHEN** the branch modifies `runner/agent.py` and `tests/conftest.py`
- **THEN** the 🔀 message contains a ⚠️ sensitive-paths section listing both files, and still offers ✅ Merge, ❌ Reject and 💬 Request changes

#### Scenario: File moved out of a sensitive directory
- **WHEN** the branch renames `runner/verify.py` to `tools/verify.py`
- **THEN** `runner/verify.py` is listed as a sensitive path

#### Scenario: Unusual file name or case
- **WHEN** the branch adds `runner/évil.py` or `.Claude/settings.json`
- **THEN** the file is listed as a sensitive path

#### Scenario: Ordinary change
- **WHEN** the branch changes only `bot.py`, `tests/test_meal_picker.py` and `openspec/changes/<name>/`
- **THEN** the 🔀 message has no sensitive-paths section

#### Scenario: Many sensitive files
- **WHEN** 20 sensitive files changed
- **THEN** 15 are listed, followed by "…and 5 more"

### Requirement: Diff-only review hint
The 🔀 message SHALL give the review command `git -C <MAIN> diff main...review/<change-name>` and
SHALL state that the branch must not be checked out in the main checkout.

#### Scenario: Hint content
- **WHEN** a 🔀 message is sent for `add-meal-picker`
- **THEN** it contains `diff main...review/add-meal-picker` and a line saying not to check the branch out in the main checkout

### Requirement: Review branches are never pushed
The runner SHALL NOT push review branches, or any other ref, to a git remote, and SHALL NOT
require git remote credentials.

#### Scenario: Merge request sent
- **WHEN** the runner creates or updates a review branch
- **THEN** no `git push` is executed and no remote is contacted
