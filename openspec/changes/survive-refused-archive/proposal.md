# Survive a refused openspec archive

## Problem
After merging `restore-command-hints-feedback-args`, `openspec archive` refused to run because
`openspec/specs/command-hints/spec.md` had no Purpose section. It exits 0 when it refuses, so the
runner went on to commit nothing, `git commit` failed and the tick crashed after the merge, before
resolving the feedback or restarting the bot. Every later tick would hit the same crash.

## Goals
- When the change is still in `openspec/changes/` after archiving, the runner warns the admin with
  openspec's output and finishes the merge path (resolve, restart, `merged`) instead of crashing.

## Non-goals
- Validating specs before merging.
