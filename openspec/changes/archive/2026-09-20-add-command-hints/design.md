# Design: Command Hint Improvements

## Context
The bot already supports `/start`, `/help`, `/feedback`, and `/cancel`. The issue is not missing functionality; it is discoverability. Users need a stronger on-ramp that explains how to see Telegram command suggestions and which commands matter.

## Approach
Update the existing user-facing entry points rather than adding new UI:
1. `start()` should explicitly mention typing `/` to reveal command suggestions.
2. `help_command()` should list the commands and reinforce the same hint.
3. Command descriptions should remain concise and match the in-chat wording.

## Why this approach
- It addresses the feedback with the smallest possible behavior change
- It preserves the current bot flow and state handling
- It is easy to verify manually and unlikely to regress other behavior

## Risks
- Telegram clients vary in how prominently they show command suggestions
- Copy-only changes may not fully satisfy users who want a richer onboarding flow
