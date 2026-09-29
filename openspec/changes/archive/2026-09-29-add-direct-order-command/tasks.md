## 1. Implementation

- [ ] 1.1 Add `MAX_ORDER_QUERY_LEN = 50` and a pure `normalize_order_query(text)` helper in `bot.py` that collapses whitespace, strips, and truncates the text
- [ ] 1.2 Extract a shared `build_order_keyboard(food)` that builds the `InlineKeyboardMarkup` from `build_order_links`, and use it in `meal_picker` without changing `/meal` behaviour
- [ ] 1.3 Add an async `order_command` handler: join `context.args`, normalize the text, reply with the usage hint (no keyboard) if it is empty, otherwise reply with one plain-text message naming the food plus the order keyboard
- [ ] 1.4 Register `CommandHandler("order", order_command)`, add `BotCommand("order", ...)` to the command suggestions, and add an `/order` line to the `/help` text

## 2. Tests

- [ ] 2.1 Unit tests for `normalize_order_query`: whitespace collapsing, trimming, 50-char truncation, empty input
- [ ] 2.2 Handler test: `/order 牛肉麵` sends one reply containing 牛肉麵 with two buttons ("Uber Eats", "foodpanda") whose URLs use the expected prefixes and contain `%E7%89%9B%E8%82%89%E9%BA%B5`
- [ ] 2.3 Handler test: `/order` with no args sends the usage hint mentioning `/order` and `/meal`, with no `reply_markup`
- [ ] 2.4 Handler test: multi-word and overlong input produce the normalized, encoded query with no raw spaces
- [ ] 2.5 Tests that `/order` appears in the `BotCommand` list and `/help` text, and that the existing `/meal` tests still pass
- [ ] 2.6 Run the full test suite (`python -m pytest`) and confirm it is green
