# Add Calculator Feature

## Problem

A user requested a calculator feature directly through the feedback flow:
> "I need a calculator feature" / "I really need a calculator"

The bot currently only handles feedback collection. Adding a calculator gives users
a useful utility inside the same Telegram interface without leaving the chat.

## Proposal

Add a `/calc` command that evaluates a basic arithmetic expression typed by the user
and replies with the result. The interaction is single-turn: user sends `/calc 2 + 3`,
bot replies `5`.

## Goals

- Let users evaluate basic arithmetic expressions inline in Telegram
- Keep the implementation small and self-contained (no new dependencies)
- Follow the existing command pattern (`/start`, `/help`, `/feedback`, `/cancel`)

## Non-goals

- No multi-turn conversation or stateful calculator session
- No scientific functions (sin, cos, log, etc.)
- No expression history or memory registers
- No changes to the feedback flow

## Success Criteria

- `/calc 2 + 3` replies `5`
- `/calc` with no expression replies with usage instructions
- Invalid expressions reply with a clear error instead of crashing
- The command appears in `/help` and Telegram's command list
