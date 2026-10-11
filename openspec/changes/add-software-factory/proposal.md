# Add a software factory

## Problem
Features for the bot reach `main` two ways today: the autonomous runner (feedback-driven, one agent per
step) and a person driving Claude Code by hand. There is no small, visible pipeline where a person can
hand Claude Code a feature and watch it go through a spec, a build and independent reviews before it
is merged.

## Goals
- One Claude Code skill, `/factory`, that runs a fixed loop: spec-writer → builder → four parallel
  reviewers (security, UX, UI, code) → approver → merge or needs-human.
- Agents talk only through markdown files in `factory/jobs/<job-id>/`; the orchestrator alone writes
  `factory/board.json`.
- A one-file dashboard that shows jobs moving through the loop and lets you read every file.
- Small enough that a viewer understands the whole thing in a few minutes.

## Non-goals
- Replacing the autonomous runner or its sandbox. The factory runs in a person's own Claude Code session.
- Pushing to GitHub. Merges are local; the person pushes.
- Changing the bot itself.

## Success criteria
- `/factory <feature>` takes a feature to `merged` or `needs-human` with every intermediate file on disk.
- The dashboard, served from `factory/`, shows each review round as chips that fill in as verdicts land.
- Factory jobs never change the Hermes integration, the runner or `requirements.txt` (same boundary
  as `guard-hermes-from-runner`).
