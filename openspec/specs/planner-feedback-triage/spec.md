# planner-feedback-triage Specification

## Purpose
Define how the planner reads the actionable feedback queue via `ask.py`, decides whether feedback needs clarification, and uses clarification outcomes when recommending work.
## Requirements
### Requirement: Actionable queue via ask.py
`python ask.py next` SHALL print JSON with three fields:
- `actionable`: the actionable submissions, in priority order
- `pending_approval`: the number of clarifications waiting for the admin
- `parked`: the number of clarifications sent and not yet answered

A submission SHALL be excluded from `actionable` if it has a `resolved` or `wont_do` event, or if it has an in-flight autonomous run. `python ask.py next --user <id>` SHALL restrict `actionable` to submissions from that user.

#### Scenario: Resolved feedback excluded
- **WHEN** a submission has a `resolved` event
- **THEN** it does not appear in `actionable`

#### Scenario: Won't-do feedback excluded
- **WHEN** a submission has a `wont_do` event
- **THEN** it does not appear in `actionable`

#### Scenario: In-flight run excluded
- **WHEN** a submission has an `auto_runs` row that is not `merged` or `rejected`
- **THEN** it does not appear in `actionable`

#### Scenario: Filter by submitter
- **WHEN** `ask.py next --user 908274693` is run, and actionable submissions exist from several users
- **THEN** `actionable` contains only submissions from user 908274693, in the usual priority order

#### Scenario: Answered clarifications first
- **WHEN** one older submission has no clarification and one newer submission has an `answered` clarification
- **THEN** the newer, answered submission is listed first

#### Scenario: Clarification context included
- **WHEN** an actionable submission has an `answered` or `discarded` clarification
- **THEN** its entry includes the clarification status, question, and answer text if answered

#### Scenario: Empty queue
- **WHEN** no submissions are actionable
- **THEN** `actionable` is an empty list and the counts are still reported

### Requirement: Planner skill uses the clarification loop
The `planner-fetch-feedback` skill SHALL instruct the planner to:
- get feedback only through `ask.py next`
- apply an ambiguity gate before proposing work
- draft at most one clarification per submission, following the question-writing rules

#### Scenario: Ambiguous feedback without clarification
- **WHEN** the top actionable item has no clarification and different readings would lead to different features
- **THEN** the planner drafts a question with `ask.py draft`, reports it as awaiting approval, and moves on to the next actionable item

#### Scenario: Clear feedback
- **WHEN** all reasonable readings of the top item lead to the same feature
- **THEN** the planner recommends a change without asking

#### Scenario: Answered clarification
- **WHEN** the top item has an `answered` clarification
- **THEN** the planner uses the answer and checks the item against the current OpenSpec specs, not the state at the time of asking

#### Scenario: Discarded clarification
- **WHEN** the top item has a `discarded` clarification
- **THEN** the planner proceeds with its best interpretation and records it as an explicit assumption

#### Scenario: Pending work reported
- **WHEN** `ask.py next` reports pending-approval or parked counts above zero
- **THEN** the planner's brief includes those counts

### Requirement: Question-writing rules
The skill SHALL require clarification drafts to:
- quote the submitter's own words
- offer mutually exclusive options that each lead to different work
- use plain, non-technical language
- be written in the same language as the original feedback

#### Scenario: Non-English feedback
- **WHEN** the feedback is written in Chinese
- **THEN** the drafted question and options are in Chinese

### Requirement: Skill available to both agent setups
The skill SHALL exist under both `.github/skills/planner-fetch-feedback/` and `.claude/skills/planner-fetch-feedback/`. Both planner agent definitions SHALL reference it.

#### Scenario: Claude Code planner
- **WHEN** the Claude Code planner agent (`.claude/agents/planner.md`) runs
- **THEN** its instructions direct it to use the `planner-fetch-feedback` skill

#### Scenario: Copilot planner
- **WHEN** the Copilot planner agent (`.github/agents/planner.agent.md`) runs
- **THEN** its instructions direct it to use the `planner-fetch-feedback` skill

