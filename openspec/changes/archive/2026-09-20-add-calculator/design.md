# Design: Add Calculator Feature

## Approach

Single-turn `/calc <expression>` command. No conversation handler needed —
a plain `CommandHandler` is sufficient since the expression arrives in the
same message as the command (via `context.args`).

Expression evaluation uses Python's `ast` module to parse and walk the
expression tree safely, without calling `eval()`. Only numeric literals and
the operators `+`, `-`, `*`, `/`, `//`, `%`, `**`, and unary `+`/`-` are
permitted. Any other node type raises a `ValueError`.

## Affected files

| File | Change |
|------|--------|
| `bot.py` | Add `calc` handler function and register `CommandHandler("calc", calc)` |
| `sql/init.sql` | No change |
| `storage.py` | No change |

## Data model

No persistence. Calculator results are ephemeral — not stored.

## Safe evaluation contract

```
allowed nodes: Expression, BinOp, UnaryOp, Constant (numbers only)
allowed BinOp ops: Add, Sub, Mult, Div, FloorDiv, Mod, Pow
allowed UnaryOp ops: UAdd, USub
everything else: raise ValueError("unsupported expression")
```

Division by zero is caught and returned as a user-facing error message.

## Command registration

Add to `setup_bot_commands`:
```
BotCommand("calc", "Evaluate an arithmetic expression, e.g. /calc 2 + 3")
```

Add to `/help` reply text:
```
/calc - Evaluate an arithmetic expression (e.g. /calc 2 + 3)
```

## Error handling

| Condition | Reply |
|-----------|-------|
| No expression given | `Usage: /calc <expression>\nExample: /calc 2 + 3` |
| Parse or evaluation error | `Invalid expression. Example: /calc 2 + 3` |
| Division by zero | `Error: division by zero` |
