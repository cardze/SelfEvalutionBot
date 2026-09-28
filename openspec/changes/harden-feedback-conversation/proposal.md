## Why

On 2026-09-28 three `/feedback` replies timed out on the way to Telegram (`ConnectTimeout` /
`ReadTimeout`, python-telegram-bot's default 5 s timeouts, no retry). Because the form's step only
advances when the handler returns, a failed Step 2 prompt left the conversation on Step 1: the
user's next message overwrote the saved bug text, and both affected submissions (`7b0671fb`,
`e3837182`) were stored with the original bug lost and `bug_text == suggestion_text`. A failed
thank-you after storing left the user stuck on Step 2, so their next plain-text message would have
become another submission. Each failure also dumped a full traceback under "No error handlers are
registered".

## What Changes

- **Step follows saved data**: once the bug text is saved, the form moves to Step 2 even if the
  Step 2 prompt could not be delivered.
- **Retry form replies**: every reply the `/feedback` form sends (start, Step 2, thank-you, cancel)
  is retried up to 3 attempts, waiting 1 s and then 3 s, on network errors (not on permanent
  errors such as `BadRequest` or `Forbidden`).
- **Longer timeouts**: the bot's Telegram connect and read timeouts go from 5 s to 10 s.
- **Always end after storing**: once a submission is stored (or the form is cancelled), user data
  is cleared and the conversation ends, even if the confirmation reply fails.
- **Error handler**: the application registers an error handler that logs Telegram network errors
  as one line and other errors with their traceback.
- **Duplicates are allowed**: a suggestion identical to the bug text is stored as-is. With the step
  following saved data, a resend no longer loses information.

## Capabilities

### New Capabilities
- `feedback-form`: the two-step `/feedback` conversation's resilience to Telegram send failures —
  step progression, reply retries, conversation ending, and error logging.

### Modified Capabilities
- (none) — clarification capture (`feedback-clarification`) and event types
  (`feedback-event-integrity`) are unchanged; no event is added or removed.

## Impact

- **Code**: `bot.py` only — a reply-with-retry helper, the four feedback handlers, a small
  `build_application(token)` extracted from `main()` (timeouts + error handler), and the error
  handler.
- **Tests**: new `tests/test_feedback_form.py` (fake messages that time out N times; no DB).
- **Dependencies / schema**: none.
- **Out of scope**: reminder delivery (already retries every 30 s), `getUpdates` errors (the
  library retries them; they only get the shorter log line), and repairing submission `e3837182`.
