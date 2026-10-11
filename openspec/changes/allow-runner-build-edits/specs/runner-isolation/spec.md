## ADDED Requirements

### Requirement: BUILD may edit only inside its workspace
The runner's Claude settings SHALL auto-approve file edits inside the run's workspace and SHALL deny
file edits to the main checkout, the snapshot folder, `~/.seb-runner`, `~/.hermes`, `~/.claude`,
`~/.ssh`, `~/.aws` and `~/.config`.

#### Scenario: BUILD edits bot code
- **WHEN** the BUILD agent uses its Edit tool on `bot.py` in its workspace
- **THEN** the edit is applied without asking for approval

#### Scenario: Edit outside the workspace
- **WHEN** an agent uses the Write tool on a file in `~/.seb-runner`
- **THEN** the write is refused, and the pre-run self-test fails closed if it is not
