## 1. Schema and storage

- [ ] 1.1 Add the `runner_signals` table to `sql/init.sql` (design D4, incl. `users`, `impact`, `known_cause`)
- [ ] 1.2 Widen `auto_runs.decision` CHECK to include `build` (drop + re-add, idempotent)
- [ ] 1.3 Add `FeedbackService` methods: `record_signal_occurrences`, `signals_to_suggest(now, limit)`, `mark_signal_suggested`, `accept_signal(id, admin_id)` (submission + `submitted` event, idempotent), `dismiss_signal`, reset of accepted signals whose submission is resolved, `is_signal_submission(submission_id)`
- [ ] 1.4 `set_auto_run_decision`: accept `build` only in stage `planned`, and `reject` also in stage `planned`

## 2. Bot log facts (`bot.py`)

- [ ] 2.1 `_on_error` appends ` user=<id>` when the update has an effective user
- [ ] 2.2 `_reply` appends ` chat=<id>` to the not-delivered warning when the message has a chat id

## 3. Detection and impact (`runner/signals.py`)

- [ ] 3.1 Incremental reader with the `signals_offset` state file: start at EOF on first run, reset on inode change or truncation, 5 MB cap, skip a partial last line
- [ ] 3.2 Record parser: `unhandled`, `reply_failed`, `reminder_failed`; ignore `Telegram network error`
- [ ] 3.3 Fact extraction with strict validation (class, repo path, function, line hint, digit-only ids); drop invalid records and count them
- [ ] 3.4 Handler map from `<MAIN>/bot.py` (`CommandHandler` / `CallbackQueryHandler` prefixes, `reminders.py` functions, fallback "internal code")
- [ ] 3.5 Known-cause table (exact class + message match) and experience text per kind
- [ ] 3.6 Impact lines, headline and thresholds (1 for `unhandled`; 3 in 24 h for the others)

## 4. PLAN impact and build gate (runner)

- [ ] 4.1 `runner/prompts/plan.md`: require the `impact` block (`changes`, `risk`, `size`)
- [ ] 4.2 `validate.validate_plan`: require and validate `impact` (size enum, non-empty strings ≤ 300 chars)
- [ ] 4.3 `notify.planned`: show Changes / Risk / Size; for gated runs add ▶️ Build / ❌ Drop (`run:<id>:b|r`) and say the queue waits for the decision
- [ ] 4.4 `do_plan`: gated runs stop at `planned`; `handle_inflight` on `planned`: gated + `build` → BUILD, gated + `reject` → reject path, gated + none → `waiting`, non-gated → BUILD
- [ ] 4.5 `runner.py`: run scan → record → reset resolved → suggest (cap 3 / 24 h) at the start of every tick, wrapped so failures never block the tick; one-line summary in the runner log

## 5. Telegram (`bot.py`, `runner/notify.py`)

- [ ] 5.1 `notify.signal(signal)`: 💡 message per design D7 with 📋 / 🙈 (`sig:<id>:p|d`)
- [ ] 5.2 `signal_decision` handler for `^sig:` — admin only, `query.answer()` first, accept/dismiss, edit the message, "Already handled" for decided signals; register in `main()`
- [ ] 5.3 `runner_decision`: add `b` → `build` with "the build starts within an hour"

## 6. Tests

- [ ] 6.1 Parser and validation tests on fixtures in the real log format (incl. user/chat ids, injected text never reaching outputs, invalid fields dropped, polling noise ignored)
- [ ] 6.2 Reader tests: first run at EOF, rotation, truncation, partial line, 5 MB cap
- [ ] 6.3 Impact tests: handler map for the current `bot.py`, known vs unknown cause, users unknown, headline wording
- [ ] 6.4 Storage/lifecycle tests (DB-backed): thresholds, 24 h window, one open suggestion, daily cap, dismiss snooze, double-tap accept, regression after resolve, `build` decision only in `planned`
- [ ] 6.5 PLAN validation tests: missing / invalid impact fails; impact appears in 📋
- [ ] 6.6 Stage tests: gated run stops at `planned`, ▶️ builds, ❌ rejects, crash resume keeps waiting; non-gated runs unchanged; scanning failure does not block a tick
- [ ] 6.7 Bot handler tests: `sig:` non-admin ignored / accept / dismiss / already handled; `run:<id>:b`; `_on_error` and `_reply` log ids
- [ ] 6.8 Update existing tests whose fake PLAN output lacks `impact`
- [ ] 6.9 Run the full test suite (with a throwaway database) and confirm it passes
