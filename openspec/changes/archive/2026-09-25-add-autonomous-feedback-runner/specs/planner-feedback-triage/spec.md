## MODIFIED Requirements

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
