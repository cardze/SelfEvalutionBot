## ADDED Requirements

### Requirement: One clarification per submission
The system SHALL allow at most one clarification per feedback submission, enforced by a database uniqueness constraint.

#### Scenario: First draft for a submission
- **WHEN** `ask.py draft` is run for a submission that has no clarification
- **THEN** a clarification row is created with status `pending_approval`

#### Scenario: Second draft for the same submission
- **WHEN** `ask.py draft` is run for a submission that already has a clarification in any status
- **THEN** the command exits non-zero, no row is created, and no Telegram message is sent

#### Scenario: Draft for a resolved submission
- **WHEN** `ask.py draft` is run for a submission that has a `resolved` event
- **THEN** the command exits non-zero and no row is created

### Requirement: Draft validation
`ask.py draft` SHALL reject a draft before writing to the database unless all of these hold:
- the question is 1–500 characters
- there are 2–4 options
- each option is 1–30 characters
- the options contain no duplicates

#### Scenario: Too few options
- **WHEN** a draft has only one option
- **THEN** the command exits non-zero with a validation error and nothing is stored

#### Scenario: Option too long
- **WHEN** any option exceeds 30 characters
- **THEN** the command exits non-zero with a validation error and nothing is stored

#### Scenario: Duplicate options
- **WHEN** two options are identical
- **THEN** the command exits non-zero with a validation error and nothing is stored

### Requirement: Admin approval in Telegram
By default, the system SHALL send each new draft to the admin (`ADMIN_USER_ID`) as a preview before anything reaches the submitter. The preview SHALL show:
- the submitter ID
- the original feedback
- the question
- the options
- ✅ Send and ❌ Discard buttons

#### Scenario: Preview sent
- **WHEN** a valid draft is stored without `--yes`
- **THEN** the admin receives a preview with ✅ Send and ❌ Discard buttons, and the submitter receives nothing

#### Scenario: Admin approves
- **WHEN** the admin taps ✅ Send on a `pending_approval` preview
- **THEN** the question is delivered to the submitter, the status becomes `sent` with `sent_at` set, a `clarification_requested` event is recorded, and the preview is edited to show it was sent

#### Scenario: Admin discards
- **WHEN** the admin taps ❌ Discard on a `pending_approval` preview
- **THEN** the status becomes `discarded`, nothing is sent to the submitter, and the preview is edited to show it was discarded

#### Scenario: Non-admin taps approval button
- **WHEN** a user whose ID is not `ADMIN_USER_ID` triggers an approval callback
- **THEN** the callback is ignored and the clarification is unchanged

#### Scenario: Double tap on approve
- **WHEN** ✅ Send is tapped again on a clarification that is no longer `pending_approval`
- **THEN** no second message is sent to the submitter

#### Scenario: Delivery fails after approval
- **WHEN** the admin taps ✅ Send and sending to the submitter fails
- **THEN** the status reverts to `pending_approval`, no `clarification_requested` event is recorded, and the admin is told about the failure

#### Scenario: Skip approval
- **WHEN** `ask.py draft` is run with `--yes`
- **THEN** the question is delivered directly to the submitter, as if the admin had approved it

### Requirement: Question delivery format
The system SHALL deliver the question to the submitter as plain text, with no parse mode. It SHALL attach one inline button per option plus a "✏️ Something else" button.

#### Scenario: Question with special characters
- **WHEN** the question or options contain characters that are special in Markdown, such as `.`, `!` or `(`
- **THEN** the message is delivered successfully and displayed verbatim

#### Scenario: Buttons shown
- **WHEN** a question with three options is delivered
- **THEN** the submitter sees four buttons: the three options and "✏️ Something else"

### Requirement: Answer capture
The system SHALL record the submitter's first answer, whether an option tap or a free-text reply, and SHALL mark the clarification `answered`. It SHALL set `answer_text`, `answer_source` and `answered_at`, and SHALL record a `clarified` event.

#### Scenario: Option tapped
- **WHEN** the submitter taps an option button on a `sent` clarification
- **THEN** the answer is stored with `answer_source = 'option'`, a `clarified` event is recorded, and the question message is edited to confirm the choice

#### Scenario: Something else, then reply
- **WHEN** the submitter taps "✏️ Something else"
- **THEN** the bot sends a ForceReply prompt asking them to reply with their answer, stores the prompt's message ID, and the status stays `sent`

#### Scenario: Free-text reply to prompt
- **WHEN** the submitter sends a text message that replies to their stored ForceReply prompt
- **THEN** the answer is stored with `answer_source = 'free_text'`, a `clarified` event is recorded, and the message is not processed by the `/feedback` conversation

#### Scenario: Reply survives restart
- **WHEN** the bot restarts between the ForceReply prompt and the submitter's reply
- **THEN** the reply is still captured as the answer

#### Scenario: Unrelated reply during feedback flow
- **WHEN** a user in the middle of `/feedback` sends a text reply to a message that is not a stored ForceReply prompt
- **THEN** the message is handled by the `/feedback` conversation as usual

#### Scenario: Second answer
- **WHEN** an answer arrives for a clarification that is already `answered`
- **THEN** the stored answer is unchanged and the user is told it was already answered

#### Scenario: Answer from wrong user
- **WHEN** a user other than the submitter triggers an answer callback for a clarification
- **THEN** the callback is ignored

#### Scenario: Answer after submission resolved
- **WHEN** the submitter answers a clarification whose submission already has a `resolved` event
- **THEN** the answer is stored, the user is told the request was already addressed, and the submission does not appear in the actionable queue

### Requirement: Submission lifecycle from clarification state
The system SHALL derive a submission's queue state from its `resolved` events and its clarification status. It SHALL NOT use timers or expiry.

#### Scenario: Question sent parks the submission
- **WHEN** a submission's clarification is `sent`
- **THEN** the submission is excluded from the actionable queue and counted as parked

#### Scenario: Awaiting admin approval
- **WHEN** a submission's clarification is `pending_approval`
- **THEN** the submission is excluded from the actionable queue and counted as pending approval

#### Scenario: Answer reopens the submission
- **WHEN** a submission's clarification becomes `answered`, at any time after sending
- **THEN** the submission is back in the actionable queue, ahead of submissions without answered clarifications

#### Scenario: Discard keeps submission actionable
- **WHEN** a submission's clarification is `discarded`
- **THEN** the submission stays in the actionable queue in its normal `created_at` order

#### Scenario: No reply ever
- **WHEN** a `sent` clarification is never answered
- **THEN** the submission stays parked indefinitely, and no automatic action is taken
