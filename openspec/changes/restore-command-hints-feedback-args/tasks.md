## 1. Command menu

- [ ] 1.1 In `bot.start_background`, also schedule `setup_bot_commands(application)` as a task
- [ ] 1.2 Remove the manual event-loop `setup_bot_commands` block from `main()`
- [ ] 1.3 Test (tests/test_command_hints.py): `start_background` on a running loop calls `set_my_commands` once with `start` and `help` included, and still starts the reminder loop when it times out

## 2. Inline /feedback text

- [ ] 2.1 In `feedback_start`, when text follows the command, save it as the bug text, send the Step 2 prompt and return `STEP_SUGGESTION` (share logic with `feedback_bug`)
- [ ] 2.2 Tests (tests/test_feedback_form.py): `/feedback the calc is wrong` → Step 2 with bug saved and `started` recorded; `/feedback` and `/feedback   ` → Step 1; Step 2 prompt timing out still returns Step 2

## 3. Verify

- [ ] 3.1 Run the full test suite and `openspec validate restore-command-hints-feedback-args`
