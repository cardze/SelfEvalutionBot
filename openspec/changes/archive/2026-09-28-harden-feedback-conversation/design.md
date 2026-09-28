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
- `Forbidden`, `RetryAfter` and every other `TelegramError` are not retried;
- returns `True` on success and `False` on any `TelegramError` (after the last retry, or at once
  for a permanent one), logging one warning. **It never raises a `TelegramError`**, so callers need
  no `try`. Non-Telegram exceptions (programming errors) still propagate.

*Alternatives*: PTB's `AIORateLimiter` retries only `RetryAfter`; a custom `BaseRequest` subclass
would retry every call bot-wide, including clarification and runner messages, which is broader
than this change needs. A `ReadTimeout` retry may duplicate a prompt the user already received;
a duplicated prompt is preferable to a lost one.

### D2. State transitions no longer depend on the reply
Because `_reply` never raises a `TelegramError`, every handler is straight-line code:
- `feedback_start`: record `started`, `await _reply(...)`, return `STEP_BUG`. If the prompt fails
  the user can still type their bug; a repeated `/feedback` re-enters as before.
- `feedback_bug`: save `user_data["bug"]`, `await _reply(...)`, return `STEP_SUGGESTION`
  regardless of the result (including `Forbidden` / `BadRequest`).
- `feedback_suggestion`: store the submission and record `submitted` (unchanged, and still
  allowed to raise — a DB failure must not silently end the form and lose the text); then
  `await _reply(thanks)`, `user_data.clear()`, return `END`.
- `feedback_cancel`: record `cancelled`, `await _reply(...)`, `user_data.clear()`, return `END`.

*Rejected*: `try: reply finally: clear(); return END`. A `return` inside `finally` silently
discards the in-flight exception (and is a `SyntaxWarning` from Python 3.14, PEP 765), and in
PTB 20.7 a handler cannot both raise and change the conversation state.

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
- `update` may be `None` (polling errors arrive via `run_polling`'s `error_callback` with no
  update), so the handler never dereferences it.

This also shortens the existing `getUpdates` `ReadError` / `Bad Gateway` noise, since PTB passes
those to error handlers as well.

### D5. Replies captured outside the form never fall through into it
`clarification_reply` (group -1) and `runner_note_reply` (group -2) save the user's answer, reply,
then `raise ApplicationHandlerStop` so the message does not reach the `/feedback` conversation
(group 0). Today a failed reply raises before the stop, so PTB passes the same message on to
group 0 and a user who is mid-form gets the answer stored as bug or suggestion text. Both switch
to `_reply`, so the stop is always reached once the answer is saved.

## Risks / Trade-offs

- [A handler blocks up to ~64 s during an outage (3 × (10 s connect + 10 s read) + 4 s of waits),
  and PTB processes updates sequentially by default] → Other users' updates queue behind it.
  Acceptable for a small bot: during such an outage their replies would fail anyway.
- [Step 2 prompt never delivered; the user resends the bug text] → Stored as bug = suggestion = X.
  Redundant but lossless, and allowed by design.
- [`ReadTimeout` retries duplicate a delivered prompt] → The user sees Step 2 twice. Harmless.
- [`store_submission` succeeds but recording the `submitted` event fails] → The handler raises,
  the form stays on Step 2, and a resend stores a second submission. Same as today; rare (two
  consecutive local DB calls), and out of scope.
- [`feedback_start` prompt never delivered] → The user may not know the form started; their next
  plain text is taken as the bug. Same as today, minus the stuck state.

## Migration Plan

Code-only; merge and restart the bot (launchd KeepAlive). Rollback by reverting the merge.
Users mid-conversation at restart lose in-memory form state, as with any restart today.
