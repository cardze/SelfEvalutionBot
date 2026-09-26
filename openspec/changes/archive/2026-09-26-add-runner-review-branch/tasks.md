## 1. Git helpers (`runner/refs.py`)

- [x] 1.1 Add `review_branch(change_name) -> "refs/heads/review/<name>"`
- [x] 1.2 Add `set_review_branch(config, change_name, ref)`: resolve `ref` to a sha and `update-ref` the review branch to it; skip and return a warning reason if the branch is checked out in any worktree (`git worktree list --porcelain`)
- [x] 1.3 Add `delete_review_branch(config, change_name)`: `update-ref -d` with `check=False`; same checked-out guard as 1.2
- [x] 1.4 Add `SENSITIVE_PREFIXES` / `SENSITIVE_FILES` / `SENSITIVE_BASENAMES` constants and a pure, case-insensitive `sensitive_paths(paths) -> list[str]`
- [x] 1.5 Add `changed_paths(config, ref)` using `diff --name-only -z --no-renames --no-ext-diff --no-textconv main...<ref>`

## 2. Runner stages (`runner/runner.py`)

- [x] 2.1 `do_build`: delete the review branch at BUILD start (when `change_name` is set)
- [x] 2.2 `do_build`: after verification passes, set the review branch, then set stage `awaiting_decision`, then compute sensitive paths and pass them to `notify.merge_request`; send ⚠️ if the checked-out guard fired
- [x] 2.3 `merge_path`: delete the review branch after a successful merge, next to `refs.delete_ref`; leave it on abort
- [x] 2.4 `reject_path`: delete the review branch (only when `change_name` is set, also when `<MAIN>` is not on `main`)

## 3. Merge request message (`runner/notify.py`)

- [x] 3.1 Add the ⚠️ sensitive-paths section (cap 15, "…and N more", omitted when empty)
- [x] 3.2 Replace the "Review locally" hint with the diff-only hint using `review/<change-name>`

## 4. Tests

- [x] 4.1 Unit tests for `sensitive_paths`: each prefix/file/basename, nested `conftest.py`, upper/mixed case, a non-sensitive look-alike (e.g. `runner_notes.md`, `docs/AGENTS.md`)
- [x] 4.2 Stage test: after a straight-through run, `review/<name>` equals `refs/runner/<id>`
- [x] 4.3 Stage test: changes path deletes the branch at BUILD start and recreates it at the new commit
- [x] 4.4 Stage tests: branch gone after merge and after reject; kept after a full-suite failure
- [x] 4.5 Stage test: stale `review/<name>` is overwritten
- [x] 4.6 Git-level tests (no DB) for `set_review_branch` / `delete_review_branch` / `changed_paths` on temp repos: create, overwrite, delete, checked-out guard (main and linked worktree), non-ASCII path, rename out of `runner/`
- [x] 4.6a Stage tests: reject of a PLAN-failed run (no change name) does not crash; reject while `<MAIN>` is on another branch still deletes the review branch
- [x] 4.7 Message tests (no DB; stub `notify.send` and `FeedbackService.update_auto_run`): sensitive section present for `runner/…` + rename-out-of-`runner/`, absent for an ordinary change, capped at 15; hint contains `diff main...review/<name>`
- [x] 4.8 Test that no runner code path invokes `git push` (e.g. assert over recorded git calls in the stage tests)

## 5. Documentation

- [x] 5.1 Add a "Reviewing runner changes" section to `AGENTS.md`: diff / `git show` only, never check out `review/*` in the main checkout, never run git/tests/editors/Claude Code inside `SEB-*` workspaces or a worktree of a `review/*` branch outside the sandbox, `review/` namespace is runner-owned, avoid `git push --all`
- [x] 5.2 Run the full test suite and confirm it passes
