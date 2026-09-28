## 1. Order link helper

- [x] 1.1 Add `UBER_EATS_SEARCH_URL` (Uber Eats Taiwan search page, https://www.ubereats.com/tw/search with `q` param) and `FOODPANDA_SEARCH_URL` (https://www.foodpanda.com.tw/search with `q` param) constants in `bot.py` near the meal pools
- [x] 1.2 Add pure `build_order_links(meal)` returning a list of (label, url) tuples, "Uber Eats" then "foodpanda", using `urllib.parse.quote(meal)`

## 2. Handler and help

- [x] 2.1 Update `meal_picker` to reply with the unchanged combo text plus a `reply_markup` `InlineKeyboardMarkup` holding one row of URL `InlineKeyboardButton` objects built from `build_order_links(meal)`
- [x] 2.2 Update the `/help` `/meal` line to mention Uber Eats / foodpanda links (keep the BotCommand description unchanged)

## 3. Tests

- [x] 3.1 In `tests/test_meal_picker.py`, test `build_order_links` returns two entries in order with the correct base URL prefixes
- [x] 3.2 Test a Chinese meal (牛肉麵) is percent-encoded and URLs contain no raw non-ASCII or space characters
- [x] 3.3 Test the handler reply: extend the fake `reply_text` to capture `reply_markup`; assert one reply, one row of two URL buttons labelled "Uber Eats" and "foodpanda", URLs contain the encoded selected meal and not the drink (patch `build_meal_combo` for determinism)
- [x] 3.4 Test `/help` text mentions Uber Eats and foodpanda; confirm existing meal-picker tests still pass
- [x] 3.5 Run the full test suite (`python -m pytest`) and fix regressions
