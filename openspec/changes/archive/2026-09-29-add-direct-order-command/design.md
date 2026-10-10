## Context

`bot.py` already has `build_order_links(meal)`, a pure function returning `[("Uber Eats", url), ("foodpanda", url)]` from static Taiwan search URL constants with `urllib.parse.quote(meal, safe="")`. `meal_picker` turns that into an `InlineKeyboardMarkup`. The feedback asks for direct ordering; real checkout automation is not feasible (no public API, needs credentials and payment data), so this change adds the next useful step: order links for food the user names.

## Goals / Non-Goals

**Goals:**
- `/order <food>` returns Uber Eats and foodpanda search buttons for `<food>` in one message.
- Reuse `build_order_links`; keep the handler stateless and offline.
- Leave `/meal` unchanged.

**Non-Goals:**
- Login, cart, payment, delivery address, or placing orders.
- Restaurant lookup, scraping, or calling platform APIs.
- Per-user favourites or order history.

## Decisions

- **Separate `/order` command** instead of `/meal <food>`: keeps the existing `/meal` spec ("extra arguments are ignored") intact and makes the intent explicit.
- **Food text source**: `" ".join(context.args)`. If the normalized text is empty, reply with a usage hint and no keyboard.
- **Normalization helper** `normalize_order_query(text) -> str`: collapse whitespace, strip, truncate to `MAX_ORDER_QUERY_LEN = 50` characters. Pure and unit-testable; encoding stays in `build_order_links`.
- **Reply text**: e.g. a line like "幫你找 {food}：點下方按鈕到外送平台下單", with the keyboard built as in `meal_picker`. Sent as plain text (no parse mode) so user text cannot inject markup.
- **Keyboard helper**: extract `build_order_keyboard(food)` so `meal_picker` and `order_command` share it; no behaviour change for `/meal`.

## Risks / Trade-offs

- The user may still expect true auto-ordering. Mitigation: documented as link-based; full ordering needs its own change.
- Arbitrary user text in URLs is safe because `quote(..., safe="")` encodes everything, and length is capped.
- Platform search URLs may change; they are constants shared with `/meal`, so a fix is a one-line change.
