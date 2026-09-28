## ADDED Requirements

### Requirement: Form step follows saved data
The `/feedback` form SHALL move to Step 2 as soon as the bug text is saved, whether or not the
Step 2 prompt was delivered. A suggestion identical to the saved bug text SHALL be stored as-is.

#### Scenario: Step 2 prompt fails to send
- **WHEN** a user in Step 1 sends "the calc is wrong" and every attempt to send the Step 2 prompt fails with a timeout
- **THEN** the conversation is in Step 2, and the user's next text message is stored as the suggestion with bug text "the calc is wrong"

#### Scenario: User resends the bug text
- **WHEN** the Step 2 prompt failed and the user sends the same text again
- **THEN** a submission is stored with bug text and suggestion text both equal to that text

### Requirement: Form replies are retried on network errors
The bot SHALL attempt every reply the `/feedback` form sends (the Step 1 prompt, the Step 2
prompt, the thank-you and the cancel confirmation) up to 3 times, waiting 1 second before the
second attempt and 3 seconds before the third, when the attempt fails with a Telegram network
error (including timeouts). Permanent errors — `BadRequest`, `Forbidden` — and `RetryAfter` SHALL NOT be
retried.

#### Scenario: Transient timeout
- **WHEN** the Step 2 prompt times out once and then succeeds
- **THEN** the prompt is sent exactly twice, with a 1 second wait between attempts

#### Scenario: Persistent timeout
- **WHEN** all 3 attempts to send a form reply time out
- **THEN** no further attempt is made, one warning is logged, and the handler does not raise

#### Scenario: Permanent error
- **WHEN** sending a form reply fails with `BadRequest`
- **THEN** it is not retried

### Requirement: Telegram request timeouts
The bot SHALL use a 10 second connect timeout and a 10 second read timeout for its Telegram
requests.

#### Scenario: Application settings
- **WHEN** the bot application is built
- **THEN** its request connect timeout and read timeout are both 10 seconds

### Requirement: Form ends once stored or cancelled
After a submission has been stored, or the form has been cancelled, the bot SHALL clear the
user's form data and end the conversation, even if the confirmation reply could not be delivered.
If storing the submission itself fails, the conversation SHALL NOT end.

#### Scenario: Thank-you fails after storing
- **WHEN** the submission is stored and every attempt to send the thank-you fails
- **THEN** the conversation has ended, the form data is cleared, and the user's next plain-text message is not stored as feedback

#### Scenario: Cancel confirmation fails
- **WHEN** the user sends `/cancel` and the confirmation cannot be delivered
- **THEN** a `cancelled` event is recorded and the conversation has ended

#### Scenario: Storage fails
- **WHEN** storing the submission raises a database error
- **THEN** the conversation stays in Step 2 with the bug text kept

### Requirement: Error handler logs network errors in one line
The bot SHALL register an application error handler. Telegram network errors (other than
`BadRequest`) SHALL be logged as a single warning line naming the error type and message, without
a traceback. All other errors SHALL be logged at error level with their traceback.

#### Scenario: Timeout reaches the error handler
- **WHEN** an update fails with `telegram.error.TimedOut`
- **THEN** exactly one warning line is logged and no traceback is logged

#### Scenario: Programming error
- **WHEN** an update fails with a `KeyError`
- **THEN** an error-level log entry with the traceback is written
