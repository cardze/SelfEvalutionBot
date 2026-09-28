## Context

`/feedback` is a `ConversationHandler` (`bot.py`): `feedback_start` → `STEP_BUG` →
`feedback_bug` → `STEP_SUGGESTION` → `feedback_suggestion` → `END`, with `/cancel` as fallback.
Each handler awaits `update.message.reply_text(...)` and then returns the next state.

In python-telegram-bot 20.7, a blocking handler that raises leaves the conversation in its old
state. So today:

```
feedback_bug:        user_data["bug"] = X ; reply ✗ → raise → state stays STEP_BUG
next message S:      handled as the bug again → X overwritten
feedback_suggestion: store ; record ; reply ✗ → raise → clear()/END never run → stuck on Step 2
```

The application is built with default request settings (5 s connect / 5 s read, no retry) and
has no error handler, so every failure logs "No error handlers are registered" plus a traceback.

## Goals / Non-Goals

**Goals:**
- The form's state always reflects what has been saved, never whether a reply got through.
- Transient Telegram failures on form replies are retried a few times before giving up.
- A stored or cancelled form never leaves the user inside the conversation.
- Network errors produce one log line.

**Non-Goals:**
- Rejecting or re-prompting when the suggestion equals the bug (explicitly allowed).
- Reminder delivery, `getUpdates` handling, clarification messages, other commands' replies.
- Queueing undelivered replies for later, or detecting whether a `ReadTimeout` was delivered.
- Repairing already-stored submissions.

## Decisions

### D1. `_reply(message, text, **kwargs) -> bool` with bounded retry
One module-level helper in `bot.py` wraps `message.reply_text`:
- up to **3 attempts**, sleeping **1 s** then **3 s** (`_REPLY_DELAYS = (1, 3)`) via `asyncio.sleep`
  (patchable in tests);
- retries on `telegram.error.NetworkError` (this includes `TimedOut`) **except** `BadRequest`,
  which is a `NetworkError` subclass in PTB but is permanent (e.g. bad MarkdownV2);
- `Forbidden`, `RetryAfter` and any other exception are not retried;
- returns `True` on success, `False` after the last retryable failure (logged as one warning);
  non-retryable exceptions propagate unchanged.

*Alternatives*: PTB's `AIORateLimiter` retries only `RetryAfter`; a custom `BaseRequest` subclass
would retry every call bot-wide, including clarification and runner messages, which is broader
than this change needs. A `ReadTimeout` retry may duplicate a prompt the user already received;
a duplicated prompt is preferable to a lost one.

### D2. State transitions no longer depend on the reply
- `feedback_bug`: save `user_data["bug"]`, `await _reply(...)`, return `STEP_SUGGESTION`
  regardless of the result.
- `feedback_suggestion`: store the submission and record `submitted` (unchanged, and still
  allowed to raise — a DB failure must not silently end the form and lose the text); then
  `try: await _reply(thanks) finally: user_data.clear(); return END`.
- `feedback_cancel`: record `cancelled`, then the same `try/finally` clear and `END`.
- `feedback_start`: record `started`, `await _reply(...)`, return `STEP_BUG`. If the prompt fails
  the user can still type their bug; a repeated `/feedback` re-enters as before.

Because `_reply` returns `False` rather than raising for retryable errors, the `finally` blocks
only matter for non-retryable exceptions (e.g. `Forbidden`), which still propagate to the error
handler after the conversation ends.

### D3. Timeouts: 10 s connect and read
`Application.builder().token(token).connect_timeout(10).read_timeout(10).post_init(_post_init)`.
These apply to regular bot calls (replies); `getUpdates` keeps its own `get_updates_*` settings.
The builder call moves into `build_application(token) -> Application`, which `main()` uses, so a
test can check the timeouts and the error handler without starting polling.

### D4. Error handler
`application.add_error_handler(_on_error)`:
- `NetworkError` (not `BadRequest`): `logger.warning("Telegram network error: %s: %s", type, err)`
  — one line, no traceback.
- anything else: `logger.error("Unhandled error", exc_info=context.error)` — real bugs keep their
  traceback.

This also shortens the existing `getUpdates` `ReadError` / `Bad Gateway` noise, since PTB passes
those to error handlers as well.

## Risks / Trade-offs

- [A handler blocks up to ~64 s during an outage (3 × (10 s connect + 10 s read) + 4 s of waits),
  and PTB processes updates sequentially by default] → Other users' updates queue behind it.
  Acceptable for a small bot: during such an outage their replies would fail anyway.
- [Step 2 prompt never delivered; the user resends the bug text] → Stored as bug = suggestion = X.
  Redundant but lossless, and allowed by design.
- [`ReadTimeout` retries duplicate a delivered prompt] → The user sees Step 2 twice. Harmless.
- [`feedback_start` prompt never delivered] → The user may not know the form started; their next
  plain text is taken as the bug. Same as today, minus the stuck state.

## Migration Plan

Code-only; merge and restart the bot (launchd KeepAlive). Rollback by reverting the merge.
Users mid-conversation at restart lose in-memory form state, as with any restart today.
