## Context

`runner/refs.py` fetches `auto/<id>` from the workspace into `refs/runner/<id>` in the main checkout
(`<MAIN>`) and does all inspection there, under `<MAIN>`'s trusted git config (design D11 of
`add-autonomous-feedback-runner`). `refs/runner/*` is outside `refs/heads/*`, so branch lists,
editors and the Claude app's diff pane never show it.

`<MAIN>` is also where launchd starts both the bot (`<MAIN>/bot.py`) and the runner
(`<MAIN>/runner/run.sh`); `runner.py` reads its stage prompts from `<MAIN>`'s working tree. So the
working tree of `<MAIN>` *is* the trusted code. Anything that changes it — like checking out an
agent branch — hands the agent's code the runner's privileges (OAuth token, Telegram token,
database).

Nothing currently restricts which paths an agent may edit. The admin's ✅ is the only gate, and the
🔀 message shows a diffstat without highlighting security-relevant files.

## Goals / Non-Goals

**Goals:**
- Make the change under review visible as an ordinary local branch, so any diff tool can show it.
- Keep that branch exactly in sync with what the latest 🔀 message describes.
- Point out edits to files that control execution or trust, so the admin reads them closely.
- Add no new way for agent-controlled code or config to run outside the sandbox.

**Non-Goals:**
- Pushing to GitHub or opening pull requests (considered and deferred — see D5).
- Blocking ✅ or adding a second confirmation for sensitive paths.
- Technically preventing a human from checking the branch out in `<MAIN>` (not possible from code
  that the checkout would itself replace — see Risks).
- Restricting which paths agents may edit.

## Decisions

### D1. Name: `review/<change-name>`
`change_name` is already validated as `^[a-z0-9]+(-[a-z0-9]+)*$`, ≤100 chars, so it is always a
valid ref component. It is more readable than the run id in branch pickers and matches the
OpenSpec folder. The `review/` prefix marks the branch as "look, don't check out" and reserves a
namespace: the runner may overwrite or delete any `review/*` branch it manages.
*Alternative*: `review/<id-prefix>` — unique by construction, but meaningless in a branch list.
Only one run is in flight at a time, so name collisions between live runs cannot happen.

### D2. Created only when 🔀 is sent; written with `update-ref`, not `branch`
The branch is set in `do_build` right after verification passes and just before
`notify.merge_request`, to the commit `refs/runner/<id>` resolves to:
`git -C <MAIN> update-ref refs/heads/review/<name> <sha>` (with `refs.SAFE` flags).
`update-ref` touches only the ref — no hooks, no working tree — and overwrites a stale branch of
the same name. Creating it earlier (after PLAN, or on every fetch) would show commits that were
never offered for review.

### D3. Lifecycle
| Event | Review branch |
|---|---|
| BUILD passes, 🔀 sent | created / moved to the reviewed commit |
| BUILD starts again (changes path, retry with note, crash resume) | deleted |
| Merge succeeds | deleted, together with `refs/runner/<id>` |
| Merge aborted (tests / conflict) | kept — the 🔀 decision is still pending |
| Reject | deleted, together with `refs/runner/<id>` |

Deleting at BUILD start (instead of only overwriting at the next 🔀) means a failed rebuild never
leaves a branch that silently disagrees with the latest messages.
If `<MAIN>`'s `HEAD` is the review branch itself, the runner does not move or delete it and sends a
⚠️ warning instead: moving a checked-out branch with `update-ref` would desync the working tree.

### D4. Sensitive-path warning
Changed paths come from `git -C <MAIN> diff --name-only --no-renames --no-ext-diff --no-textconv
main...<ref>`. `--no-renames` lists both sides of a move, so moving a file *out of* `runner/` is
still flagged. A path is sensitive if it:
- starts with `runner/`, `.claude/`, `.github/` or `.vscode/`, or
- equals `AGENTS.md`, `CLAUDE.md`, `.envrc`, `requirements.txt` or `sql/init.sql`, or
- has basename `conftest.py`.

The list lives in one constant in `runner/refs.py`, with a pure `sensitive_paths(paths)` function so
it is unit-testable without git. The 🔀 message adds, before "Tests:":
```
⚠️ Touches sensitive paths — read these diffs closely:
runner/agent.py
.claude/settings.json
…and 3 more
```
capped at 15 paths. With none, the section is omitted. Warn only: buttons and the ✅ gate are
unchanged, because ✅ is already a deliberate admin action and a second confirmation adds a new
decision state for little gain.

### D5. Never push
The runner holds no git remote credentials and gains none. Reviewing on GitHub would need
credentials in the trusted process, would publish agent code outward, and would let a future
branch add `.github/workflows/*` that run with repo secrets on push. It would also create a second
Merge button that skips the post-✅ database suite and archiving. Deferred to a separate change if
ever wanted.

### D6. Review hint and AGENTS.md
The 🔀 "Review locally" line becomes:
```
Review by diff (never check out in the main checkout):
git -C <MAIN> diff main...review/<name>
```
`AGENTS.md` documents the review rules for humans and agents (diff / `git show` only; no checkout
in `<MAIN>`; no git, tests, editors or Claude Code inside `SEB-*` workspaces outside the sandbox).

## Risks / Trade-offs

- [Admin checks out `review/*` in `<MAIN>`] → The next hourly tick runs the branch's
  `runner/run.sh` and `runner/*.py` with full privileges; a bot restart runs its `bot.py`. Code
  cannot guard this, because the guard lives in the tree being replaced. → Mitigated by the
  `review/` name, the hint in every 🔀 message, AGENTS.md, and the sensitive-path warning showing
  whether `runner/` was touched at all.
- [`git push --all` / `--mirror` by the admin publishes review branches] → Documented in
  AGENTS.md. Default `push.default=simple` does not push them.
- [A human-made branch named `review/<x>` is overwritten] → The `review/` namespace is reserved for
  the runner (AGENTS.md).
- [Sensitive-path list is incomplete] → It is a reading aid, not a control; ✅ remains the gate.
  Extending it is a one-line change.
- [Runner crashes between merge and cleanup] → Leaves a stale `review/*` branch; harmless, and the
  next 🔀 with the same name overwrites it.

## Migration Plan

Implemented and merged by hand through the normal interactive flow (this change modifies the
runner itself, so it is not runner-built). No data migration. Existing in-flight runs get a review
branch at their next 🔀; the current `awaiting_decision` run (if any) simply has none until then.
Rollback: revert the merge; leftover `review/*` branches can be deleted with `git branch -D`.
