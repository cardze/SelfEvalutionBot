# Test the merge result before merging

## Problem
Every runner merge since the Hermes backend landed is aborted with "1 skipped". The post-approval
full suite runs on a `git archive` export with no `.git`, so `test_repo_snapshot_exports` (which read
the real checkout's `main` branch) skips, and any skip fails the run. A run built before a fix lands
on `main` also keeps failing, because the suite only sees the run's own commit.

## Goals
- `test_repo_snapshot_exports` builds its own git repo and never skips.
- The post-approval suite runs on the tree the merge will produce (`main` merged with the approved
  commit), so fixes on `main` count and conflicts are caught before merging.

## Non-goals
- Relaxing the "any skip fails" rule.
