## ADDED Requirements

### Requirement: Best-effort clearing of decision buttons
After a runner decision tap is recorded, the bot SHALL try to remove the buttons from the runner message. If Telegram rejects that edit, the bot SHALL log a warning and SHALL NOT let the error escape the handler. The recorded decision and the admin's acknowledgement SHALL be unaffected.

#### Scenario: Buttons already cleared
- **WHEN** the admin taps ✅ Merge, the decision is recorded, and Telegram rejects the button removal with `BadRequest`
- **THEN** the handler completes without raising, the merge decision remains stored, the admin is told the runner will act within an hour, and a warning is logged

#### Scenario: Normal clear
- **WHEN** the admin taps ✅ Merge and the edit succeeds
- **THEN** the buttons are removed from the message
