## ADDED Requirements

### Requirement: A job moves through a fixed loop
`/factory <feature>` SHALL create `factory/jobs/<job-id>/` and run spec-writer, builder, four reviewers
in parallel, and approver, in that order, recording the stage in `factory/board.json`.

#### Scenario: All reviewers pass
- **WHEN** every review in a round starts with `VERDICT: PASS` and the approver writes `APPROVE`
- **THEN** `factory/<job-id>` is merged into `main` locally and the job's stage is `merged`

#### Scenario: A reviewer asks for changes
- **WHEN** any review in round n starts with `VERDICT: CHANGES` and fewer than 2 reworks have run
- **THEN** the orchestrator waits for all four files of round n, resumes `builder-<job-id>`, and runs round n+1

#### Scenario: Reworks run out
- **WHEN** round 3 still has a `CHANGES` verdict
- **THEN** the approver writes `ESCALATE` and the job's stage is `needs-human`

### Requirement: People decide escalated jobs
`/factory approve <job-id>` SHALL merge a `needs-human` job, and `/factory rework <job-id> <note>` SHALL
send it back to the builder with the note in `rework.md` and start a new review round.

#### Scenario: Approving a job that touches Hermes
- **WHEN** a person runs `/factory approve` on a job whose diff touches `hermes_plugin/`
- **THEN** nothing is merged and the person is told to merge it by hand

### Requirement: The dashboard shows the board
`factory/dashboard.html` SHALL render every job in `board.json` as a card in its stage, show each review
round as a row of four reviewer chips, set needs-human jobs apart, and open a job's markdown files on click.

#### Scenario: A verdict lands
- **WHEN** the orchestrator sets a reviewer to `PASS` in `board.json`
- **THEN** that chip turns green within one poll
