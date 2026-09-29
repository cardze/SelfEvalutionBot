## Why

Feedback (submission 3c7b288b) repeats that the ultimate goal of `/meal` is to have the bot order directly from Uber Eats ("吳伯毅") or foodpanda ("富胖達"). The archived change `add-meal-order-links` already added one-tap search links for the *randomly picked* meal. The remaining gap is that the user can only get order links for whatever `/meal` randomly chooses; when they already know what they want, there is no way to jump straight to ordering it. Fully automated checkout is still not possible: neither platform has a public consumer ordering API, and ordering would require storing the credentials, address, and payment details of the user.

## What Changes

- New `/order <food>` command: replies with one message that confirms the requested food and carries the same "Uber Eats" / "foodpanda" inline URL buttons, searching for `<food>` instead of a random meal.
- `/order` with no text replies with a usage hint (e.g. `/order 牛肉麵`) and a pointer to `/meal` for a random pick, with no buttons.
- Food text is whitespace-normalized and capped at 50 characters before being URL-encoded; reuses the existing pure `build_order_links()` helper.
- `/order` is registered in the Telegram command suggestion list and listed in `/help`.
- `/meal` behaviour is unchanged.

**Assumptions (unattended run):**
- "Order directly" is interpreted as the shortest honest path to ordering: go straight from a food name to the platform search. The bot still does not log in, add to cart, pay, or place orders; that requires a separate, security-reviewed change and is out of scope.
- A new `/order` command is used instead of making `/meal <food>` take arguments, so the existing "extra arguments are ignored" behaviour of `/meal` stays the same.
- The 50-character cap is an arbitrary safety limit to keep URLs and replies short.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `meal-picker`: adds the `/order <food>` command that builds delivery-platform order links for user-supplied food; command discoverability covers `/order`.

## Impact

- `bot.py`: `order_command` handler, handler registration, `BotCommand` entry, `/help` line, and a small food-text normalization helper.
- `tests/test_meal_picker.py`: new tests.
- No new dependencies, DB schema, network calls, or runner changes.
