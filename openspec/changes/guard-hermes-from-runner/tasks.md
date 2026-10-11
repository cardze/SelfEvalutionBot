## 1. Guard

- [x] 1.1 `runner/guard.py`: protected paths (always and Hermes-mode) and the added-lines Hermes check
- [x] 1.2 `refs.added_lines(config, ref)` (excluding `openspec/` and `*.md`)
- [x] 1.3 Enforce after PLAN and BUILD (fail, no retry) and before merge (abort)
- [x] 1.4 State the rule in the PLAN and BUILD prompts

## 2. Hermes-mode merge and config

- [x] 2.1 Drop `setup.sh sync` from `install_requirements`
- [x] 2.2 Validate `HERMES_PROFILE` (plain name, not `default`)

## 3. Sandbox

- [x] 3.1 Deny `~/.hermes` in `runner/settings.template.json`
- [x] 3.2 Self-test check: listing `~/.hermes` is blocked

## 4. Docs

- [x] 4.1 AGENTS.md and README: what runner-built changes may not touch, and manual `setup.sh sync`
- [x] 4.2 Update `move-bot-into-hermes` spec text for the merge step

## 5. Tests

- [x] 5.1 Guard unit tests: protected paths per mode, renames, case, Hermes mentions, openspec/Markdown allowed
- [x] 5.2 Stage tests: BUILD touching the plugin fails without retry; merge of a protected ref is aborted
- [x] 5.3 Hermes-mode merge runs no `setup.sh`; config rejects `HERMES_PROFILE=default`
- [x] 5.4 Rendered settings deny `~/.hermes`; self-test includes the check
