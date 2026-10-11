# Design: guard-hermes-from-runner

## G1. Protected paths (`runner/guard.py`)
`guard.violations(config, ref)` returns human-readable reasons a runner-built commit may not be
merged, compared against `main` (`refs.changed_paths`, both sides of renames, case-insensitive).

Always protected (both `BOT_SERVICE` modes, so switching later never carries such an edit):
- `hermes_profile/`, `hermes_plugin/`, `hermes_bot.py`
- any other path whose name contains `hermes` outside `openspec/` (e.g. `runner/hermes.py`,
  `tests/test_hermes_bot.py`, a new `hermes_*.py`)

Also protected with `BOT_SERVICE=hermes`, because they run on the host or change Hermes's environment:
- `runner/` (the guard itself, the merge step, the sandbox template; executed by Hermes cron)
- `requirements.txt` (it becomes the plugin's `python_dependencies`, resolved with Hermes core)

## G2. No Hermes references in added code
Added lines (from `git diff -U0 main...ref`, excluding `openspec/` and `*.md`) that contain `hermes`
(case-insensitive) are refused, with the first few `file: line` hits. Bot code has no reason to talk to
Hermes; this stops e.g. bot code writing into `~/.hermes` or importing Hermes internals. It is a
heuristic (obfuscated strings get past it) and complements the admin's review, not replaces it.

## G3. Where it is enforced
- `do_plan`: after validation, a violation fails the run (`fail`), not retried: a plan that needs
  these paths needs a person.
- `do_build`: checked before validation and tests; a violation fails the run without retry.
- `merge_path`: re-checked on the exact ref before the full suite (the workspace is agent-controlled
  and the ref is fetched again). A violation aborts the merge (`merge_aborted`, decision cleared) and
  tells the admin.
- The PLAN and BUILD prompts state the rule so agents don't spend a run on it.

## G4. Merge in Hermes mode
`install_requirements` no longer runs `hermes_profile/setup.sh sync`. Under G1 a runner change cannot
change the plugin or `requirements.txt` in Hermes mode, so there is nothing to sync; a person who
changes them runs `hermes_profile/setup.sh sync` by hand. The merge's only Hermes command stays
`hermes -p <HERMES_PROFILE> gateway restart`. This supersedes the sync step of `move-bot-into-hermes`
design B5.

## G5. Profile name
`HERMES_PROFILE` must be a plain profile name (`[a-z0-9][a-z0-9_-]*`) and not `default`, so the
restart can never target the host gateway that serves other profiles.

## G6. Sandbox
`runner/settings.template.json` adds `~/.hermes` to the permission deny rules and `filesystem.denyRead`
(the Claude backend). The Hermes backend's tool container already mounts only the workspace. The
self-test adds a check that listing `~/.hermes` is blocked. The runner re-renders the settings file at the start of every tick, as it already does for the
Hermes profile, so the new deny applies after a `git pull` with no manual step.

## Affected files
`runner/guard.py` (new), `runner/refs.py` (`added_lines`), `runner/runner.py`, `runner/config.py`,
`runner/settings.template.json`, `runner/selftest.py`, `runner/prompts/plan.md`, `runner/prompts/build.md`,
`AGENTS.md`, `README.md`, tests.
