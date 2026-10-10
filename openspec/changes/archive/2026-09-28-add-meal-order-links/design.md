## Context

`/meal` is a stateless `CommandHandler` in `bot.py` (`meal_picker`) that calls `build_meal_combo()` and replies with one text message. The feedback end goal is automated ordering via Uber Eats or foodpanda; neither exposes a public consumer ordering API, and automating their sites would require storing credentials and payment data.

## Goals / Non-Goals

**Goals:**
- One-tap path from a `/meal` suggestion to searching that meal on Uber Eats and foodpanda.
- Keep `/meal` single-message, stateless, and offline (no outbound HTTP).
- Keep URL building a pure, unit-testable function.

**Non-Goals:**
- Placing orders, carts, account login, payment, addresses.
- Restaurant lookup or scraping; per-user platform preferences.

## Decisions

- **Inline keyboard URL buttons**: an `InlineKeyboardMarkup` with a single row of two `InlineKeyboardButton` objects using the `url` argument, instead of raw links in text. Cleaner, and no callback handler is needed.
- **Static constants** in `bot.py`: `UBER_EATS_SEARCH_URL` is the Uber Eats Taiwan search page (https://www.ubereats.com/tw/search with a `q` query parameter) and `FOODPANDA_SEARCH_URL` is the foodpanda Taiwan search page (https://www.foodpanda.com.tw/search with a `q` query parameter); the meal is appended via `urllib.parse.quote(meal)`. URL fixes become one-line changes.
- **`build_order_links(meal)`** returns a list of (label, url) tuples: "Uber Eats" first, then "foodpanda". The handler maps it to buttons, keeping Telegram types out of the pure function.
- Search by **meal only**.

## Risks / Trade-offs

- Platform search URL formats may change or not pre-fill on every client: URLs are constants; worst case the button still opens the right platform.
- User expects true auto-ordering: documented as a first step; full ordering needs its own change.
- Existing tests assert on text only: text is unchanged; the fake `reply_text` already accepts keyword arguments.
