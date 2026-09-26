## Why

Runner changes are hard to review. The runner already fetches every run into the main checkout,
but under `refs/runner/<id>`, which `git branch`, editors and the Claude app's diff pane do not show.
This pushes reviewers — people and agents — into the workspace clone (`~/github/SEB-<id>`), where
running git or the tests executes agent-controlled config and code outside the sandbox. That is
exactly what design D11 of `add-autonomous-feedback-runner` forbids for the runner itself.
The 🔀 merge request also shows only a diffstat, so an edit to the runner, agent definitions or
CI config is easy to miss.

## What Changes

- When the runner sends a 🔀 merge request, it SHALL also point a visible local branch
  `review/<change-name>` in the main checkout at the exact commit being reviewed (the same commit as
  `refs/runner/<id>`).
- The review branch is removed when BUILD starts again (💬 Request changes / 💬 Retry with note),
  and when the run is merged or rejected, so it always matches the latest 🔀 message.
- The 🔀 message gains a **⚠️ sensitive paths** section listing changed files under
  `runner/`, `.claude/`, `.github/`, `.vscode/`, or named `AGENTS.md`, `CLAUDE.md`, `.envrc`,
  `requirements.txt`, `sql/init.sql`, or `conftest.py` (anywhere). Warning only — the buttons and
  the ✅ gate are unchanged.
- The 🔀 "Review locally" hint changes to `git -C <MAIN> diff main...review/<change-name>`, with a
  reminder to review by diff and never check the branch out in the main checkout.
- The runner never pushes review branches (or anything else) to a remote.
- `AGENTS.md` gains a "Reviewing runner changes" section: review by diff / `git show`, never check
  out a `review/*` branch in the main checkout, never run git, tests or editors/Claude Code inside a
  `SEB-*` workspace outside the sandbox.

## Capabilities

### New Capabilities
- `runner-review`: how a runner-built change is exposed for review — the `review/<change-name>`
  branch and its lifecycle, the sensitive-paths warning in the 🔀 message, and the no-push rule.

### Modified Capabilities
- (none) — merge, reject and changes paths keep their existing requirements; the review branch
  cleanup is specified as an added requirement in `runner-review`.

## Impact

- **Code**: `runner/refs.py` (create/delete review branch, list changed paths),
  `runner/runner.py` (`do_build`, `merge_path`, `reject_path`), `runner/notify.py`
  (`merge_request` text).
- **Docs**: `AGENTS.md`.
- **Tests**: `tests/test_runner_stages.py` (lifecycle, message content), plus unit tests for the
  sensitive-path matcher.
- **Dependencies / schema**: none. No `auto_runs` columns, no `sql/init.sql` change.
- **Security**: no new execution surface — creating or deleting a ref runs nothing. The remaining
  risk (someone checking the branch out in the main checkout) is documented, not prevented; see
  design.md.
