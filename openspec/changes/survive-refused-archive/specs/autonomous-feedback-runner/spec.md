## MODIFIED Requirements

### Requirement: Merge path
On `decision='merge'` the runner SHALL:
1. require a clean main checkout on `main`
2. re-fetch the branch and run the complete test suite, including database tests, against a throwaway database
3. merge the fetched branch into `main` with `--no-ff`
4. archive the change with spec sync in the main checkout, and commit; if openspec refuses, warn the admin with its output and continue
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

#### Scenario: openspec refuses to archive
- **WHEN** `openspec archive` leaves the change in `openspec/changes/` (for example, an invalid spec)
- **THEN** the merge path still resolves the submission, restarts the bot and sets `merged`, and the admin receives ⚠️ with openspec's output
