## Context
`runner_decision` stores the decision and calls `query.answer(...)`. If the decision was applied, it then calls `query.edit_message_reply_markup(reply_markup=None)` to remove the buttons. Telegram can reject that edit with `BadRequest` (buttons already removed, message not editable or deleted). Nothing catches the exception today. `signal_decision` in the same file already catches `TelegramError` around its message edit and logs a warning.

## Goals / Non-Goals
- Goal: a failed button-clear never escapes the handler. The stored decision and the toast stay the same.
- Non-goal: changing callback semantics, message text, or other handlers.

## Decisions
- Catch `TelegramError` (the base class of `BadRequest`), not only `BadRequest`. Any Telegram failure while removing buttons is cosmetic, because the decision is already persisted. This matches `signal_decision`.
- Log at warning level, worded like the existing "Could not update the suggestion message" message.
- Keep the edit after `query.answer`, so the toast is sent first and the callback cannot go stale.

## Risks / Trade-offs
- If the edit fails, stale buttons can stay on screen. Tapping them again returns "This run is not awaiting a decision.", because `set_auto_run_decision` returns False. That is acceptable.
