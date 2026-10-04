# runner-signals Specification

## Purpose
How the runner turns the bot's own problem events into 💡 suggestions: the bot records structured events computed from exception objects (never log or message text), the runner validates them against `main` and counts them with an exact cursor, each suggestion states the problem's impact, and an accepted suggestion becomes admin feedback whose run waits after PLAN for ▶️ Build or ❌ Drop.
## Requirements
### Requirement: Bot records structured problem events
The bot SHALL append one JSON object per line to a dedicated events file (not the text log) when
a handler raises an error that is not a transient Telegram network error (`unhandled`), when a
form reply gives up (`reply_failed`), and when a reminder send fails (`reminder_failed`). Every
field SHALL be computed from the exception object and code location — exception class, the
deepest in-repository frame (file relative to the repository, function, line), the affected user
or chat id, and a known-cause key from exact matching — and the exception message or any other
text SHALL NOT be written. Writing SHALL never raise into the bot.

#### Scenario: Unhandled error in a command
- **WHEN** `meal_picker` raises `telegram.error.BadRequest("Message to be replied not found")` for user 908274693
- **THEN** one line is appended with kind `unhandled`, exc `telegram.error.BadRequest`, file `bot.py`, func `meal_picker`, user 908274693, known cause `reply_target_gone`, and no message text

#### Scenario: Newlines in user-influenced text
- **WHEN** an exception message contains newlines and text shaped like a log record or an event
- **THEN** exactly one event line is written for that error, and it contains none of that text

#### Scenario: Events file not configured
- **WHEN** the events file is not configured (as in any test run)
- **THEN** nothing is written

#### Scenario: Test frames are never recorded
- **WHEN** an error's deepest in-repository frame is in a file under `tests/`
- **THEN** that frame is not used as the event's location

#### Scenario: Events file not writable
- **WHEN** the events file's directory does not exist or cannot be written
- **THEN** the bot continues normally and no exception reaches the handler

#### Scenario: Polling errors are not recorded
- **WHEN** the error handler receives a transient `NetworkError` from polling
- **THEN** no event is written

### Requirement: Runner validates events and never reads log text
The runner SHALL read signals only from the events file and SHALL accept an event only if it is a
valid JSON object of a known kind and version, its timestamp has a timezone and is not in the
future, its exception class matches `^[A-Za-z_][\w.]{0,100}$`, its file (if any) is tracked by git
on `main` in the main checkout and is not under `site-packages` or `tests/`, its function (if any) matches
`^\w{1,100}$` and is defined in that file on `main`, its ids are non-negative integers, and its
known-cause key (if any) exists. Invalid events SHALL be dropped and counted. The runner SHALL NOT
read the bot's text log. Scanning SHALL run first in every tick, SHALL NOT count against the
throttle, and an error during scanning SHALL NOT stop the rest of the tick.

#### Scenario: Forged function name
- **WHEN** an event names function `ignore_all_rules` in `bot.py`, which is not defined there on `main`
- **THEN** the event is dropped and no signal changes

#### Scenario: Untracked file
- **WHEN** an event names a file that is not tracked by git on `main`
- **THEN** the event is dropped

#### Scenario: Scanner failure does not block work
- **WHEN** scanning raises an exception and an admin submission is actionable
- **THEN** the tick still starts work on that submission

### Requirement: Exact, non-replaying event cursor
The runner SHALL keep its position in the events file in the database and update it in the same
transaction as the occurrences it covers. On its first scan it SHALL start at the end of the
file. If the file was rotated or truncated it SHALL read the new file from the start. It SHALL
read at most 5 MB per tick and process only complete lines.

#### Scenario: First scan
- **WHEN** the runner scans for the first time and the file already contains events
- **THEN** no occurrences are recorded for those events

#### Scenario: Crash between read and commit
- **WHEN** the runner fails after reading events but before committing
- **THEN** the next scan records those events exactly once

#### Scenario: Rotation
- **WHEN** the events file is replaced by a new, shorter file
- **THEN** the next scan reads the new file from its start

#### Scenario: Partial line
- **WHEN** the last line of the file has no trailing newline yet
- **THEN** it is not processed until a later scan sees it complete

### Requirement: Suggestions contain only fixed text and validated facts
Signal suggestions and the submissions created from them SHALL be rendered only from fixed
template text, the fixed known-cause explanations, and validated event fields (exception class,
repository file, function, line, counts, times, number of distinct ids).

#### Scenario: Exception message never appears
- **WHEN** an unhandled `ValueError("ignore previous instructions")` occurs
- **THEN** neither the 💡 message nor any resulting submission contains `ignore previous instructions`

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
cause only when the event carries a known-cause key, and SHALL output only that key's fixed
explanation.

#### Scenario: Command handler error
- **WHEN** an `unhandled` signal is in function `meal_picker`, registered as `CommandHandler("meal", meal_picker)`, seen twice for one user
- **THEN** the suggestion names `/meal`, says the user probably gets no reply, and reports 1 user and 2 times

#### Scenario: Known cause
- **WHEN** the event has known cause `reply_target_gone`
- **THEN** the suggestion includes that key's fixed explanation and nothing from the exception message

#### Scenario: Conversation step
- **WHEN** an `unhandled` signal is in `feedback_bug`, a state of the `/feedback` conversation
- **THEN** the suggestion names `/feedback`

#### Scenario: Unknown cause
- **WHEN** the event has no known-cause key
- **THEN** the suggestion has no cause line

#### Scenario: Users unknown
- **WHEN** no user or chat id was logged for a signal's occurrences
- **THEN** the suggestion says users are unknown

### Requirement: Admin decides each suggestion
Each suggestion SHALL be a Telegram message to the admin with 📋 Plan a fix and 🙈 Dismiss buttons.
Only the admin's taps SHALL be acted on. 📋 SHALL store a feedback submission authored by the
admin, with the templated summary as bug text and a templated fix request as suggestion text,
record a `submitted` event, and link it to the signal, all in one transaction that only
succeeds while the signal is still `suggested`. 🙈 SHALL snooze the signal: it is suggested
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
When that submission is marked `wont_do` (dropped at PLAN or rejected at merge), the signal SHALL
become `dismissed`. An accepted signal SHALL NOT be suggested again while its submission is open.

#### Scenario: Regression after fix
- **WHEN** an accepted signal's submission is resolved and the same signal occurs again
- **THEN** a new suggestion is sent once its threshold is met

#### Scenario: Dropped work
- **WHEN** the admin taps ❌ Drop on the plan of an accepted signal's run
- **THEN** the signal becomes `dismissed` and follows the 7-day snooze rule

