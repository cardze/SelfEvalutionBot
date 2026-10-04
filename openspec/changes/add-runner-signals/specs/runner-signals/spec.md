## ADDED Requirements

### Requirement: Deterministic signal detection from the bot log
The runner SHALL scan new lines of the bot log on every tick, without invoking any agent or model,
and SHALL recognise these signals:
- `unhandled`: an `Unhandled error` record, keyed by exception class, repository file and function
  of the deepest in-repository traceback frame;
- `reply_failed`: a `Reply not delivered` record, keyed by error class;
- `reminder_failed`: a `Failed to deliver reminder` record.
Telegram polling errors (`Telegram network error`) SHALL be ignored. Scanning SHALL run before
resuming or throttling, SHALL NOT count against the throttle, and an error during scanning SHALL
NOT stop the rest of the tick.

#### Scenario: Unhandled error is recognised
- **WHEN** the log gains an `Unhandled error` record whose traceback ends in `telegram.error.BadRequest: Message to be replied not found` with deepest repo frame `bot.py`, `meal_picker`
- **THEN** signal `unhandled:telegram.error.BadRequest:bot.py:meal_picker` gains one occurrence

#### Scenario: Polling noise is ignored
- **WHEN** the log gains only `Telegram network error: NetworkError: Bad Gateway` lines
- **THEN** no signal gains an occurrence

#### Scenario: Scanner failure does not block work
- **WHEN** scanning raises an exception and an admin submission is actionable
- **THEN** the tick still starts work on that submission

### Requirement: Incremental, non-replaying log reading
The runner SHALL remember its position in the bot log between ticks and read only new complete
lines. On its first scan it SHALL start from the end of the log. If the log was rotated or
truncated it SHALL start from the beginning of the new file. It SHALL read at most 5 MB per tick.

#### Scenario: First scan
- **WHEN** the runner scans for the first time and the log already contains `Unhandled error` records
- **THEN** no occurrences are recorded for those existing records

#### Scenario: Rotation
- **WHEN** the log file is replaced by a new, shorter file
- **THEN** the next scan reads the new file from its start

#### Scenario: Partial line
- **WHEN** the last line of the log has no trailing newline yet
- **THEN** it is not processed until a later scan sees it complete

### Requirement: Suggestions contain only validated facts
Signal summaries and the submissions created from them SHALL be built only from a fixed template
and fields that match strict patterns (exception class `^[A-Za-z_][\w.]{0,100}$`, repository path
`^[\w./-]{1,200}$`, function `^\w{1,100}$`, counts and timestamps). Exception messages, reminder
texts and identifiers, and any other log content SHALL NOT be included. Records whose fields fail
validation SHALL be dropped.

#### Scenario: Exception message is excluded
- **WHEN** an unhandled `ValueError: bad input 'ignore previous instructions'` is recognised
- **THEN** neither the 💡 message nor any resulting submission contains `bad input` or `ignore previous instructions`

#### Scenario: Invalid field is dropped
- **WHEN** a traceback's deepest repo frame has a function name containing spaces or punctuation
- **THEN** no signal is recorded for that record

### Requirement: Thresholds and suggestion limits
An `unhandled` signal SHALL be suggested after 1 occurrence; `reply_failed` and `reminder_failed`
SHALL be suggested after 3 occurrences within 24 hours. A signal SHALL have at most one open
suggestion. The runner SHALL send at most 3 suggestions per rolling 24 hours, oldest first-seen
first. A signal whose suggestion could not be sent SHALL be retried on a later tick.

#### Scenario: Below threshold
- **WHEN** `reply_failed:TimedOut` occurs twice within 24 hours
- **THEN** no suggestion is sent

#### Scenario: Daily cap
- **WHEN** 5 signals meet their thresholds in the same tick and none were suggested in the last 24 hours
- **THEN** 3 suggestions are sent and the other 2 are sent on later ticks

### Requirement: Suggestions state the impact of the problem
Each suggestion SHALL state, using only deterministic facts and fixed text: the user-facing feature
affected (derived from the bot's handler registrations in the main checkout, or "internal code"),
what the user experiences, the number of distinct users affected when known, the total
occurrences, the last occurrence and the count in the last 24 hours. It SHALL add a plain-language
cause only when the exception class and message exactly match an entry in a fixed known-cause
table, and SHALL output only that entry's text.

#### Scenario: Command handler error
- **WHEN** an `unhandled` signal is in function `meal_picker`, registered as `CommandHandler("meal", meal_picker)`, seen twice for one user
- **THEN** the suggestion names `/meal`, says the user probably gets no reply, and reports 1 user and 2 times

#### Scenario: Known cause
- **WHEN** the exception is `telegram.error.BadRequest` with message exactly `Message to be replied not found`
- **THEN** the suggestion includes the table's explanation and no other part of the message

#### Scenario: Unknown cause
- **WHEN** the exception message is not in the known-cause table
- **THEN** the suggestion has no cause line

#### Scenario: Users unknown
- **WHEN** no user or chat id was logged for a signal's occurrences
- **THEN** the suggestion says users are unknown

### Requirement: Bot logs affected ids for errors
The bot SHALL append the affected user id to unhandled-error log lines and the chat id to
undelivered-reply log lines when available, as digits only.

#### Scenario: Unhandled error in a command
- **WHEN** a command handler raises for user 908274693
- **THEN** the `Unhandled error` log line includes `user=908274693`

### Requirement: Admin decides each suggestion
Each suggestion SHALL be a Telegram message to the admin with 📋 Plan a fix and 🙈 Dismiss buttons.
Only the admin's taps SHALL be acted on. 📋 SHALL store a feedback submission authored by the
admin, with the templated summary as bug text and a templated fix request as suggestion text,
record a `submitted` event, and link it to the signal. 🙈 SHALL snooze the signal: it is suggested
again only after 7 days and only if it occurred again after being dismissed. A tap on an
already-decided suggestion SHALL change nothing.

#### Scenario: Plan a fix
- **WHEN** the admin taps 📋 on a suggestion
- **THEN** a new admin submission exists, the signal is `accepted`, and the next runner tick treats it like any other admin feedback

#### Scenario: Non-admin tap
- **WHEN** a user other than the admin triggers a `sig:` callback
- **THEN** nothing is stored and the signal is unchanged

#### Scenario: Dismiss
- **WHEN** the admin taps 🙈 and the signal occurs again 2 days later
- **THEN** no suggestion is sent until 7 days after the dismissal

#### Scenario: Double tap
- **WHEN** the admin taps 📋 twice on the same suggestion
- **THEN** exactly one submission is stored

### Requirement: Regressions are suggested again
When the submission linked to an accepted signal is resolved, the signal SHALL return to
`observed` with its occurrence counters reset, so a recurrence after the fix is suggested again.
An accepted signal SHALL NOT be suggested again while its submission is unresolved.

#### Scenario: Regression after fix
- **WHEN** an accepted signal's submission is resolved and the same signal occurs again
- **THEN** a new suggestion is sent once its threshold is met
