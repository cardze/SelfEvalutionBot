## 1. Reply helper and application setup (`bot.py`)

- [x] 1.1 Add `_REPLY_DELAYS = (1, 3)`, a `_sleep` wrapper, and `async def _reply(message, text, **kwargs) -> bool`: up to 3 attempts, retry on `NetworkError` except `BadRequest`, return `False` with one warning on any `TelegramError` (never raise it), let non-Telegram exceptions propagate
- [x] 1.2 Extract `build_application(token) -> Application` from `main()` with `.connect_timeout(10).read_timeout(10)` and `post_init(_post_init)`; `main()` uses it
- [x] 1.3 Add `async def _on_error(update, context)`: one-line warning for `NetworkError` (not `BadRequest`), `logger.error(..., exc_info=context.error)` otherwise, never touching `update` (may be `None`); register it in `build_application`

## 2. Feedback handlers (`bot.py`)

- [x] 2.1 `feedback_start`: use `_reply`; return `STEP_BUG`
- [x] 2.2 `feedback_bug`: save the bug, `_reply` the Step 2 prompt, return `STEP_SUGGESTION` regardless of the result
- [x] 2.3 `feedback_suggestion`: keep store + `submitted` event before the reply (may raise); then `_reply` the thank-you, clear `user_data`, return `END` (no `try/finally`)
- [x] 2.4 `feedback_cancel`: record `cancelled`, `_reply`, clear, return `END`
- [x] 2.5 `clarification_reply` and `runner_note_reply`: use `_reply` so `ApplicationHandlerStop` is always raised once the answer is saved

## 3. Tests (`tests/test_feedback_form.py`, no DB)

- [x] 3.1 Fake message whose `reply_text` fails N times with a given exception; patch `bot._sleep` to record delays; stub `bot.feedback_service`
- [x] 3.2 `_reply`: success first try; one `TimedOut` then success (2 attempts, delays [1]); 3 `NetworkError`s (returns False, delays [1, 3], one warning); `BadRequest`, `Forbidden`, `RetryAfter` → one attempt, returns False; a non-Telegram exception propagates
- [x] 3.3 `feedback_bug` returns `STEP_SUGGESTION` and keeps the bug when every attempt times out, and when the reply fails with `Forbidden`
- [x] 3.4 `feedback_suggestion` stores bug == suggestion as-is; returns `END` and clears `user_data` when the thank-you times out or fails with `Forbidden`; propagates and keeps the bug when storing raises
- [x] 3.5 `feedback_cancel` records `cancelled` and returns `END` when the confirmation fails
- [x] 3.6 `build_application("123:abc")` has connect/read timeouts of 10 s and `_on_error` registered
- [x] 3.7 `_on_error`: `TimedOut` with `update=None` → one warning line, no traceback; `KeyError` → error with `exc_info`
- [x] 3.8 `clarification_reply` and `runner_note_reply` raise `ApplicationHandlerStop` when their acknowledgement times out

## 4. Verification

- [x] 4.1 Run the full test suite and confirm it passes
