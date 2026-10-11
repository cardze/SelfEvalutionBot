## Why
A runner signal reported an unhandled `telegram.error.BadRequest` in `bot.py` → `runner_decision` (line 578). That line is `query.edit_message_reply_markup(reply_markup=None)`, which runs after the decision is already stored. Telegram refuses that edit in normal cases: the buttons are already gone ("Message is not modified", for example after a double tap or a second admin client), or the message is too old or was deleted. The exception then escapes the handler. The decision is saved, but the error is logged as unhandled and raised as a signal again.

## What Changes
- In `runner_decision`, wrap the button-clearing edit in `try/except TelegramError` and log a warning. `signal_decision` already does the same.
- The decision is still recorded and the admin still gets the toast. Only the edit that removes the buttons can fail, and it now fails quietly.
- Add a regression test where the edit raises `BadRequest`.

## Capabilities
### New Capabilities
_None._
### Modified Capabilities
- `autonomous-feedback-runner`: clearing the decision buttons is best-effort and never fails the tap.

## Impact
- Code: `bot.py` (`runner_decision`), `tests/test_runner_handlers.py`.
- No new dependencies. No schema change.

## Assumptions
- The root cause is the edit at line 578, not the earlier `query.answer`. The signal names line 578. The reported cause (buttons already removed, or the message can't be edited) is inferred, because the exact error text is not in the feedback.
- No change to the 💬 path. It does not edit the message.
