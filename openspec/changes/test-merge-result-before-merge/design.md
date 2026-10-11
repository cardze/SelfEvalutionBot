# Design

`runner/testdb.run_full_suite` computes `git merge-tree --write-tree main <ref>` in the main checkout
(trusted git config, `refs.SAFE`) and exports that tree instead of `<ref>`. A conflict, or no tree,
returns "the change conflicts with main" before any venv or database is created. The tree contains
only the approved commit and `main`; uncommitted workspace files are still excluded.

`tests/test_runner_hermes.py::test_repo_snapshot_exports` copies `.claude/` into a temporary repo on
`main` instead of reading the checkout's own git.
