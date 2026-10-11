## 1. Fix
- [x] 1.1 In `bot.py` `runner_decision`, wrap `await query.edit_message_reply_markup(reply_markup=None)` in `try/except TelegramError as exc:` with `logger.warning("Could not clear the runner decision buttons: %s", exc)`

## 2. Tests
- [x] 2.1 In `tests/test_runner_handlers.py`, add a test where the fake query's `edit_message_reply_markup` raises `telegram.error.BadRequest("Message is not modified")` on a ✅ tap. Assert that the handler does not raise, the decision is recorded, and the toast is "Queued; the runner acts within an hour."
- [x] 2.2 Run `pytest tests/test_runner_handlers.py` and the full suite. Existing tests must still pass.
