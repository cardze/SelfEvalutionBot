# reminder-notifications Specification

## Purpose
TBD - created by archiving change add-reminder-notifications. Update Purpose after archive.
## Requirements
### Requirement: Schedule a one-time reminder
The bot SHALL let a user schedule a one-time reminder for a specific future time via `/remind <when> <message>`, where `<when>` is either a relative offset (`in 10m`, `in 2h`, `in 3d`) or an absolute time of day (`at 14:30`).

#### Scenario: User schedules a relative one-time reminder
- **WHEN** a user sends `/remind in 10m Take the bread out`
- **THEN** the bot confirms the reminder was scheduled and stores it as a non-recurring reminder due 10 minutes from now

#### Scenario: User schedules an absolute one-time reminder
- **WHEN** a user sends `/remind at 14:30 Call the dentist`
- **THEN** the bot confirms the reminder was scheduled for 14:30 (today if that time hasn't passed yet, otherwise tomorrow)

#### Scenario: Missing message or time
- **WHEN** a user sends `/remind` with no arguments, or `/remind in 10m` with no message text
- **THEN** the bot replies with a usage message showing the accepted `/remind` formats and does not create a reminder

#### Scenario: Unparseable time expression
- **WHEN** a user sends `/remind sometime soon Water the plants`
- **THEN** the bot replies with an error indicating the time expression could not be understood, without creating a reminder

### Requirement: Schedule a repeating notice
The bot SHALL let a user schedule a repeating notice on a fixed interval via `/remind every <interval> <message>` (e.g. `every 1h`, `every 30m`, `every 1d`), which SHALL keep firing at that interval until the user cancels it.

#### Scenario: User schedules a repeating notice
- **WHEN** a user sends `/remind every 1h Drink water`
- **THEN** the bot confirms a repeating notice was scheduled every 1 hour and stores it as recurring with its next occurrence 1 hour from now

#### Scenario: Interval below the minimum is rejected
- **WHEN** a user sends `/remind every 10s Ping me`
- **THEN** the bot replies with an error stating the minimum allowed interval and does not create the notice

### Requirement: Deliver due reminders as Telegram messages
The bot SHALL periodically check for reminders that are due and deliver each as a Telegram message to the user who created it, within the delivery loop's polling interval.

#### Scenario: One-time reminder fires
- **WHEN** a non-recurring reminder's due time has passed at the time of a delivery poll
- **THEN** the bot sends the reminder's message text to the owning user and marks the reminder as delivered so it does not fire again

#### Scenario: Repeating notice fires and reschedules
- **WHEN** a recurring notice's next occurrence time has passed at the time of a delivery poll
- **THEN** the bot sends the notice's message text to the owning user and advances its next occurrence by its configured interval, leaving it active for the following cycle

#### Scenario: Delivery failure does not lose the reminder
- **WHEN** sending the Telegram message for a due reminder fails (e.g. the user blocked the bot)
- **THEN** the bot logs the failure and does not crash the delivery loop, and the reminder is left in a state where it can be retried or inspected rather than silently discarded

### Requirement: List and cancel reminders
The bot SHALL let a user list their own active reminders and notices via `/reminders`, and cancel one they own via `/reminders cancel <id>`.

#### Scenario: User lists their reminders
- **WHEN** a user with at least one active reminder sends `/reminders`
- **THEN** the bot replies with each reminder's id, message text, next-fire time, and whether it repeats

#### Scenario: User has no reminders
- **WHEN** a user with no active reminders sends `/reminders`
- **THEN** the bot replies that they have no active reminders

#### Scenario: User cancels their own reminder
- **WHEN** a user sends `/reminders cancel <id>` for a reminder they own
- **THEN** the bot deactivates the reminder, confirms cancellation, and it no longer appears in `/reminders` or fires

#### Scenario: User cancels a reminder they do not own or that does not exist
- **WHEN** a user sends `/reminders cancel <id>` for an id that does not exist or belongs to another user
- **THEN** the bot replies with a clear error and does not modify any reminder

### Requirement: Interpret and display reminder times in Asia/Taipei
The bot SHALL interpret `at HH:MM` in `/remind` as a wall-clock time in the Asia/Taipei timezone (UTC+8), and SHALL display every reminder next-fire time (in `/remind` confirmations and `/reminders` listings) converted to Asia/Taipei, regardless of the timezone the underlying value is stored in.

#### Scenario: Absolute time is interpreted as Asia/Taipei
- WHEN a user sends `/remind at 09:00 Standup` and the current time in Asia/Taipei has not yet reached 09:00 today
- THEN the bot schedules the reminder for 09:00 Asia/Taipei time today and confirms using an Asia/Taipei-labeled time

#### Scenario: Listing shows Asia/Taipei times
- WHEN a user sends `/reminders` and has at least one active reminder
- THEN each listed next-fire time is shown converted to Asia/Taipei, not UTC or another timezone

### Requirement: Cap active reminders per user
The bot SHALL limit each user to at most 20 active reminders (one-time and repeating combined) and SHALL reject creating a new reminder that would exceed this cap with a clear error, without creating the reminder.

#### Scenario: User is at the cap
- WHEN a user who already has 20 active reminders sends a valid `/remind` command
- THEN the bot replies that the maximum number of active reminders has been reached and does not create a new reminder

#### Scenario: User is under the cap
- WHEN a user with fewer than 20 active reminders sends a valid `/remind` command
- THEN the bot creates the reminder as normal

### Requirement: Reject offsets and intervals over 365 days
The bot SHALL reject `/remind in <n>` and `/remind every <n>` expressions whose total duration exceeds 365 days, replying with a clear error naming the limit and not creating the reminder.

#### Scenario: Relative offset over the maximum is rejected
- WHEN a user sends `/remind in 400d Check the roof`
- THEN the bot replies with an error stating the maximum allowed offset and does not create a reminder

#### Scenario: Repeat interval over the maximum is rejected
- WHEN a user sends `/remind every 400d Renew the lease`
- THEN the bot replies with an error stating the maximum allowed interval and does not create the notice

