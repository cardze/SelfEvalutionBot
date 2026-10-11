## Why

A user reported: "I want the hints for original command to come back" and asked that "the text
after the command feedback should also be treated as first input." Since the bot moved into the
gateway, the Telegram `/` menu is set only by the gateway's own command list: `/start` and `/help`
are missing and some descriptions differ from the bot's (e.g. `/meal`). `bot.setup_bot_commands`
— the original menu with hints — is only called by `python bot.py`. Separately, `/feedback the calc
is wrong` ignores "the calc is wrong" and asks Step 1 again.

## What Changes

- `bot.start_background(application)` also schedules `setup_bot_commands(application)`, so the
  original command menu (with `/start` and `/help` hints) is registered in both run modes. The
  separate event-loop call in `main()` is removed, since `main()` already runs `start_background`
  through `post_init`.
- `/feedback <text>` stores `<text>` as the Step 1 bug text and goes straight to Step 2. Plain
  `/feedback` behaves as today.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `command-hints`: the original command menu is registered whenever the bot's background starts.
- `feedback-form`: text after `/feedback` counts as the Step 1 answer.

## Impact

- `bot.py` only (`start_background`, `main`, `feedback_start`), plus tests in
  `tests/test_command_hints.py` and `tests/test_feedback_form.py`.
- No new dependencies. Gateway files are not touched.

## Assumptions

- "Hints for original command" means the `/` command menu entries and descriptions that
  `setup_bot_commands` sets (welcome/help hint text is unchanged and still present).
- If the gateway resets the menu *after* the bot's background starts, our menu could be replaced
  again. Fixing that needs a change to the gateway integration file, which this autonomous run may
  not edit; a person would need to align that file's command list.
