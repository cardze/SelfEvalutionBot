## Context

`setup_bot_commands` (bot.py) sets the original Telegram menu and swallows errors. It runs only in
`main()` through a hand-made event loop before polling. The gateway path calls
`bot.start_background` once the Telegram app is running, but never sets the menu. `feedback_start`
ignores the text after the command.

## Goals / Non-Goals

**Goals:** original menu registered in both run modes; `/feedback <text>` skips Step 1.

**Non-Goals:** changing menu wording, editing gateway integration files, changing Step 2 or storage.

## Decisions

- **D1 – Register the menu from `start_background`.** It already runs on the live event loop in
  both modes (`post_init` for `bot.py`, gateway connect for the plugin). Add
  `asyncio.create_task(setup_bot_commands(application))` next to the reminder loop task. Remove the
  manual loop block in `main()` so the menu is set once. `setup_bot_commands` already logs and
  continues on failure, so a failed call cannot stop startup.
- **D2 – Inline text as Step 1.** In `feedback_start`, after recording `started`, take the message
  text after the command (`text.split(maxsplit=1)[1]`, keeping newlines; empty/whitespace means no
  text). If present: save it as `context.user_data["bug"]`, send the Step 2 prompt with the
  existing `_reply`, return `STEP_SUGGESTION` (share the logic with `feedback_bug`). Otherwise
  unchanged.

## Risks / Trade-offs

- [Gateway may set its own menu after ours] → documented in proposal; needs a person to edit the
  gateway command list if it happens.
- [Menu now set on every start, not only before polling] → idempotent Telegram call; harmless.
