"""Tests for the safe calculator (_eval_expr) and calc handler."""

import ast
import pytest
from bot import _eval_expr


def _parse(expr):
    return ast.parse(expr, mode="eval")


def test_addition():
    assert _eval_expr(_parse("2 + 3")) == 5


def test_subtraction():
    assert _eval_expr(_parse("10 - 4")) == 6


def test_multiplication():
    assert _eval_expr(_parse("3 * 7")) == 21


def test_true_division():
    assert _eval_expr(_parse("10 / 4")) == 2.5


def test_floor_division():
    assert _eval_expr(_parse("10 // 3")) == 3


def test_modulo():
    assert _eval_expr(_parse("10 % 3")) == 1


def test_power():
    assert _eval_expr(_parse("2 ** 8")) == 256


def test_unary_neg():
    assert _eval_expr(_parse("-5 + 3")) == -2


def test_unary_pos():
    assert _eval_expr(_parse("+5")) == 5


def test_nested():
    assert _eval_expr(_parse("(2 + 3) * 4")) == 20


def test_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        _eval_expr(_parse("1 / 0"))


def test_invalid_string():
    with pytest.raises((ValueError, TypeError)):
        _eval_expr(_parse("'hello'"))


def test_disallowed_call():
    with pytest.raises((ValueError, AttributeError)):
        _eval_expr(ast.parse("abs(-1)", mode="eval"))


def test_integer_display():
    result = _eval_expr(_parse("4.0"))
    text = str(int(result) if isinstance(result, float) and result.is_integer() else result)
    assert text == "4"
