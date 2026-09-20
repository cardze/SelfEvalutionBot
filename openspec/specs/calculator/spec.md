# Spec: calculator

## Capability

`calculator` — evaluate a basic arithmetic expression and return the result.

## Behaviour

### Happy path

- Input: `/calc 2 + 3` → reply: `5`
- Input: `/calc 10 / 4` → reply: `2.5`
- Input: `/calc 2 ** 8` → reply: `256`
- Input: `/calc -5 + 3` → reply: `-2`
- Integer results are displayed without a decimal point (`5`, not `5.0`).

### No expression

- Input: `/calc` (no args) → reply contains "Usage: /calc <expression>"

### Invalid expression

- Input: `/calc hello` → reply contains "Invalid expression"
- Input: `/calc 1 + ` → reply contains "Invalid expression"
- Input: `/calc __import__('os')` → reply contains "Invalid expression"

### Division by zero

- Input: `/calc 1 / 0` → reply contains "division by zero"

## Security constraint

Expression evaluation MUST NOT use `eval()` or `exec()`. Only `ast`-based
safe evaluation is permitted. Any AST node type not in the allowlist raises
a `ValueError` before evaluation proceeds.
