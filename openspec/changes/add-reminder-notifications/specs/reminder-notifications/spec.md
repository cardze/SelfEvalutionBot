## ADDED Requirements

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
