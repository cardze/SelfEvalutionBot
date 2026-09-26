## 1. Git helpers (`runner/refs.py`)

- [ ] 1.1 Add `review_branch(change_name) -> "refs/heads/review/<name>"`
- [ ] 1.2 Add `set_review_branch(config, change_name, ref)`: resolve `ref` to a sha and `update-ref` the review branch to it; skip and return a warning reason if `<MAIN>`'s `HEAD` is that branch
- [ ] 1.3 Add `delete_review_branch(config, change_name)`: `update-ref -d` with `check=False`; same checked-out guard as 1.2
- [ ] 1.4 Add `SENSITIVE_PREFIXES` / `SENSITIVE_FILES` / `SENSITIVE_BASENAMES` constants and a pure `sensitive_paths(paths) -> list[str]`
- [ ] 1.5 Add `changed_paths(config, ref)` using `diff --name-only --no-renames --no-ext-diff --no-textconv main...<ref>`

## 2. Runner stages (`runner/runner.py`)

- [ ] 2.1 `do_build`: delete the review branch at BUILD start (when `change_name` is set)
- [ ] 2.2 `do_build`: after verification passes, set the review branch, compute sensitive paths, and pass both to `notify.merge_request`; send ⚠️ if the checked-out guard fired
- [ ] 2.3 `merge_path`: delete the review branch after a successful merge, next to `refs.delete_ref`; leave it on abort
- [ ] 2.4 `reject_path`: delete the review branch next to `refs.delete_ref`

## 3. Merge request message (`runner/notify.py`)

- [ ] 3.1 Add the ⚠️ sensitive-paths section (cap 15, "…and N more", omitted when empty)
- [ ] 3.2 Replace the "Review locally" hint with the diff-only hint using `review/<change-name>`

## 4. Tests

- [ ] 4.1 Unit tests for `sensitive_paths`: each prefix/file/basename, nested `conftest.py`, a non-sensitive look-alike (e.g. `runner_notes.md`, `docs/AGENTS.md`)
- [ ] 4.2 Stage test: after a straight-through run, `review/<name>` equals `refs/runner/<id>`
- [ ] 4.3 Stage test: changes path deletes the branch at BUILD start and recreates it at the new commit
- [ ] 4.4 Stage tests: branch gone after merge and after reject; kept after a full-suite failure
- [ ] 4.5 Stage test: stale `review/<name>` is overwritten
- [ ] 4.6 Stage test: when `<MAIN>` `HEAD` is the review branch, it is not moved and a warning is sent
- [ ] 4.7 Message tests: sensitive section present for `runner/…` + rename-out-of-`runner/`, absent for an ordinary change, capped at 15; hint contains `diff main...review/<name>`
- [ ] 4.8 Test that no runner code path invokes `git push` (e.g. assert over recorded git calls in the stage tests)

## 5. Documentation

- [ ] 5.1 Add a "Reviewing runner changes" section to `AGENTS.md`: diff / `git show` only, never check out `review/*` in the main checkout, never run git/tests/editors/Claude Code inside `SEB-*` workspaces outside the sandbox, `review/` namespace is runner-owned, avoid `git push --all`
- [ ] 5.2 Run the full test suite and confirm it passes
