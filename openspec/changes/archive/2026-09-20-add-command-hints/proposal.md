# Add Command Hints

## Problem
Users can start the bot and feedback flow, but the path to discover available commands is still too implicit. The existing bot already exposes `/start`, `/help`, and Telegram command descriptions, yet the recent feedback shows a user still did not understand what hints were available while typing commands.

## Proposal
Improve command discoverability by making the bot surface concise usage hints in the places users first look:
- strengthen the `/start` message with a clear prompt to type `/` for command suggestions
- keep `/help` focused on a short command summary and a hint about Telegram's built-in command picker
- ensure the command descriptions stay aligned with the messages users see in chat

## Goals
- Reduce confusion for first-time users
- Make available commands obvious without changing the feedback conversation flow
- Keep the change small and low-risk

## Non-goals
- No new bot features beyond guidance and copy changes
- No persistence or database changes
- No redesign of the feedback workflow

## Success Criteria
- A new user can tell from `/start` how to find commands
- `/help` provides a clear, short command summary
- Existing feedback flow behavior remains unchanged
