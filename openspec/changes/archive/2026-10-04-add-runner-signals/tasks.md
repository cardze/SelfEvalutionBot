## 1. Schema and storage

- [x] 1.1 `sql/init.sql`: `runner_signals`, `runner_signal_cursor`, `auto_runs.plan_summary` / `plan_message_id`, and `build` in the `auto_runs.decision` CHECK (all idempotent, design D5)
- [x] 1.2 `FeedbackService`: `record_signal_events(events, cursor)` (occurrences + cursor in one transaction), `get_signal_cursor()`, `signals_to_suggest(now, limit)`, `mark_signal_suggested`, `accept_signal(id, admin_id)` (one transaction, D8), `dismiss_signal`, `settle_accepted_signals()` (resolved → observed with reset, wont_do → dismissed), `is_signal_submission(submission_id)`
- [x] 1.3 `set_auto_run_decision`: the exact stage/decision pairs of D12, with the gated `EXISTS` check; add `plan_summary`, `plan_message_id` to `_AUTO_RUN_FIELDS`

## 2. Event writer (`signals_events.py`, `bot.py`, `reminders.py`)

- [x] 2.1 `signals_events.py`: `KNOWN_CAUSES` (key → exc, exact message, explanation), `exception_facts(exc)` (class, deepest in-repo non-site-packages frame), `known_cause(exc)`, `record(kind, …)` appending one `json.dumps` line to `SEB_SIGNALS_FILE` only when it is set (no default), swallowing `OSError`; repo root = `Path(__file__).resolve().parent`; skip `site-packages` and `tests/` frames
- [x] 2.2 `bot._on_error`: record `unhandled` (with `effective_user.id`) for non-retryable errors only
- [x] 2.3 `bot._reply`: record `reply_failed` with the caller's frame and `message.chat_id` when it gives up
- [x] 2.4 `reminders._deliver_due`: record `reminder_failed` with the reminder's `user_id` when a send fails
- [x] 2.5 `runner/launchd/com.seb.bot.plist.template`: set `SEB_SIGNALS_FILE` to `{{HOME}}/.seb-runner/logs/signals.jsonl`

## 3. Runner detection and impact (`runner/signals.py`)

- [x] 3.1 Reader: DB cursor, first run at EOF, rotation/truncation reset, 5 MB cap, complete lines only
- [x] 3.2 Validation (D3): JSON shape, kind, version, timezone-aware non-future `ts`, `exc` pattern, file tracked on `main` (`git ls-tree`) and not under `tests/`, function defined in that file on `main`, integer ids, known-cause key; drop and count invalid events
- [x] 3.3 Fingerprints and thresholds (1 for `unhandled`; 3 in 24 h for the others)
- [x] 3.4 Handler map from `main:bot.py` (`CommandHandler`, `ConversationHandler` members → entry command, `CallbackQueryHandler` prefixes), `reminders.py` → reminder delivery, fallback "internal code"
- [x] 3.5 Renderer: headline, Impact / Who / Cause / Where lines and the submission texts (D8, D9)

## 4. Runner flow (`runner/runner.py`, `validate.py`, `notify.py`, `prompts/plan.md`)

- [x] 4.1 `tick()`: scan → record → settle accepted → suggest (cap 3 / 24 h) first, wrapped so failures never block the tick; one summary line per tick
- [x] 4.2 `prompts/plan.md` asks for `impact`; `validate.validate_plan` requires and validates it
- [x] 4.3 `notify.planned(run, submission, summary, impact, gated)`: impact lines for all runs; gated variant with ▶️ Build / ❌ Drop and the "queue waits" note; returns the message id
- [x] 4.4 `do_plan`: store summary + impact as JSON in `plan_summary`; gated runs stop at `planned` and store `plan_message_id`
- [x] 4.5 `handle_inflight` on `planned`: gated → resend if `plan_message_id` is NULL, `build` → BUILD, `reject` → reject path, else `waiting`; non-gated → BUILD
- [x] 4.6 `do_build` clears `decision` as it starts (the note is kept for build retries)
- [x] 4.7 `notify.signal(signal)`: 💡 message with 📋 / 🙈 (`sig:<id>:p|d`)

## 5. Bot callbacks (`bot.py`)

- [x] 5.1 `signal_decision` for `^sig:` — admin only, `query.answer()` first, accept / dismiss, edit the message, "Already handled"; register in `main()`
- [x] 5.2 `runner_decision`: `b` → `build` ("the build starts within an hour")

## 6. Tests

- [x] 6.1 Event writer: fields from a real exception (class, deepest repo frame, site-packages skipped, chained exception uses its own traceback, no-message exception); known-cause keys; newline/forged text in the message never written and produces exactly one line; unwritable path swallowed; nothing written when `SEB_SIGNALS_FILE` is unset; `tests/` frames skipped; polling errors not recorded
- [x] 6.2 Validation: forged function not defined in the file, untracked file, site-packages path, `tests/` path, bad `exc`, naive or future `ts`, non-integer ids, unknown known-cause key — all dropped and counted
- [x] 6.3 Reader and cursor (DB): first run at EOF, rotation, truncation, partial line, 5 MB cap at a line boundary, crash before commit records events exactly once
- [x] 6.4 Impact rendering against the current `bot.py`: `/meal`, `/feedback` for `feedback_bug`, `run:` label, reminder delivery, internal fallback, known vs no cause, users unknown; exception message never appears
- [x] 6.5 Lifecycle (DB): thresholds, 24 h window, one open suggestion, daily cap ordered by `first_seen`, dismiss snooze needs new occurrences, double-tap accept gives one submission, resolved → observed reset, wont_do → dismissed
- [x] 6.6 Decisions (DB): `build` only in `planned` on gated runs, `reject` in `planned` only when gated, `merge` never in `planned`
- [x] 6.7 Stages: gated run stops at `planned` with no BUILD; lost 📋 resent; ▶️ → BUILD; ❌ → `REJECTED.md` + `wont_do`; failed gated PLAN + 💬 re-plans and stops again; non-gated runs unchanged; scan raising still starts work
- [x] 6.8 PLAN impact: missing / invalid / over-long `impact` fails; impact shown in 📋; update fake PLAN outputs in `tests/test_runner_stages.py` and `tests/test_runner_agent.py`
- [x] 6.9 The rendered bot plist contains `SEB_SIGNALS_FILE`; the runner plist does not
- [x] 6.10 Bot: `sig:` non-admin ignored, accept, dismiss, already handled; `run:<id>:b`
- [x] 6.11 Run the full test suite (with a throwaway database) and confirm it passes
