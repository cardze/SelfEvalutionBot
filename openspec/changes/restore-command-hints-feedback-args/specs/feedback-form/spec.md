## ADDED Requirements

### Requirement: Text after /feedback is the Step 1 answer
When a user sends `/feedback` followed by text, the bot SHALL record the `started` event, save
that text (everything after the command, trimmed) as the bug text, send the Step 2 prompt and move
the conversation to Step 2. `/feedback` with no text or only whitespace SHALL show the Step 1 prompt
as before.

#### Scenario: Inline feedback text
- **WHEN** a user sends `/feedback the calc is wrong`
- **THEN** the Step 2 prompt is sent, the conversation is in Step 2, and the user's next text is stored as the suggestion with bug text "the calc is wrong"

#### Scenario: No inline text
- **WHEN** a user sends `/feedback`
- **THEN** the Step 1 prompt is sent and the conversation is in Step 1

#### Scenario: Step 2 prompt fails after inline text
- **WHEN** a user sends `/feedback the calc is wrong` and every attempt to send the Step 2 prompt times out
- **THEN** the conversation is still in Step 2 with bug text "the calc is wrong"
