## 1. Reply helper and application setup (`bot.py`)

- [ ] 1.1 Add `_REPLY_DELAYS = (1, 3)` and `async def _reply(message, text, **kwargs) -> bool`: up to 3 attempts, retry on `NetworkError` except `BadRequest`, `asyncio.sleep` between attempts, one warning after the last failure, re-raise non-retryable errors
- [ ] 1.2 Extract `build_application(token) -> Application` from `main()` with `.connect_timeout(10).read_timeout(10)` and `post_init(_post_init)`; `main()` uses it
- [ ] 1.3 Add `async def _on_error(update, context)`: one-line warning for `NetworkError` (not `BadRequest`), `logger.error(..., exc_info=context.error)` otherwise; register it in `build_application`

## 2. Feedback handlers (`bot.py`)

- [ ] 2.1 `feedback_start`: use `_reply`; return `STEP_BUG`
- [ ] 2.2 `feedback_bug`: save the bug, `_reply` the Step 2 prompt, return `STEP_SUGGESTION` regardless of the result
- [ ] 2.3 `feedback_suggestion`: keep store + `submitted` event before the reply (may raise); wrap the thank-you in `try/finally` that clears `user_data` and returns `END`
- [ ] 2.4 `feedback_cancel`: record `cancelled`, then `try/finally` around the confirmation that clears and returns `END`

## 3. Tests (`tests/test_feedback_form.py`, no DB)

- [ ] 3.1 Fake message whose `reply_text` fails N times with a given exception; patch `bot.asyncio.sleep` to record delays; stub `bot.feedback_service`
- [ ] 3.2 `_reply`: success first try; one `TimedOut` then success (2 attempts, delay 1); 3 failures (returns False, delays [1, 3], one warning); `BadRequest` and `Forbidden` not retried
- [ ] 3.3 `feedback_bug` returns `STEP_SUGGESTION` and keeps the bug when every attempt times out
- [ ] 3.4 `feedback_suggestion` stores bug == suggestion as-is; returns `END` and clears `user_data` when the thank-you fails; does not end and keeps the bug when storing raises
- [ ] 3.5 `feedback_cancel` records `cancelled` and returns `END` when the confirmation fails
- [ ] 3.6 `build_application("123:abc")` has connect/read timeouts of 10 s and `_on_error` registered
- [ ] 3.7 `_on_error`: `TimedOut` → one warning line, no traceback; `KeyError` → error with `exc_info`

## 4. Verification

- [ ] 4.1 Run the full test suite and confirm it passes
