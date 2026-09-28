## Why

Feedback (submission e3837182) says the ultimate goal of `/meal` is to let the bot place the order on Uber Eats ("吳伯毅") or foodpanda ("富胖達"). Today `/meal` only prints a random combo, so the user must open a delivery app and search manually. Fully automated ordering is not feasible now: neither platform offers a public consumer ordering API, and ordering would need the user credentials, address, and payment details, which is a large security and scope expansion. This change delivers the first concrete step: one tap from the `/meal` reply to each platform with the picked meal already searched.

## What Changes

- `/meal` reply gains an inline keyboard with two URL buttons, "Uber Eats" and "foodpanda", each opening that platform search for the selected meal (URL-encoded).
- A pure helper builds the URLs from static in-code base URL constants (no network calls, no API keys).
- Existing combo text is unchanged; the reply is still a single message.
- The `/help` line for `/meal` mentions the delivery links.

**Assumptions (unattended run):**
- "Ordering" is scoped to deep-linking into platform search; the user completes checkout themselves. Automated ordering (login, cart, payment) is out of scope and needs a separate, security-reviewed change.
- Links target the Taiwan sites (`www.ubereats.com/tw`, `www.foodpanda.com.tw`) since the meal pool is Traditional Chinese.
- Only the meal is used as the search query, not the drink.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `meal-picker`: `/meal` reply adds Uber Eats and foodpanda search links for the picked meal; help text mentions them.

## Impact

- `bot.py`: URL constants, `build_order_links(meal)` helper, `meal_picker` passes `reply_markup`, help text line.
- `tests/test_meal_picker.py`: new tests.
- No new dependencies, DB, or runner changes.
