from typing import Any

import pytest
import sympy as sp

from yasno.math.equivalence import equivalent, proportional
from yasno.math.errors import ErrorType
from yasno.math.mistakes import equation_mutations, expression_mutations
from yasno.math.parsing import Equation, Expression, parse_line

x = sp.Symbol("x", real=True)
a = sp.Symbol("a", real=True)
b = sp.Symbol("b", real=True)


def _raw(text: str) -> Any:
    statement = parse_line(text)
    assert isinstance(statement, Expression)
    return statement.raw


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((x + 1) ** 2, x**2 + 2 * x + 1, True),
        ((x**2 - 1) / (x - 1), x + 1, True),
        (sp.sqrt(x) * sp.sqrt(x), x, True),
        ((a - b) ** 2, a**2 - b**2, False),
        (sp.log(x**2), 2 * sp.log(x), True),
    ],
)
def test_equivalent(first: Any, second: Any, expected: bool) -> None:
    assert equivalent(first, second) is expected


def test_proportional() -> None:
    assert proportional(2 * x - 6, x - 3, x)
    assert not proportional(x - 6, x - 3, x)


@pytest.mark.parametrize(
    ("text", "wrong", "error"),
    [
        ("(a-b)^2", a**2 - b**2, ErrorType.DISTRIBUTION),
        ("-(x-3)", -x - 3, ErrorType.DISTRIBUTION),
        ("x^2 \\cdot x^3", x**6, ErrorType.POWERS),
        ("(x^2)^3", x**5, ErrorType.POWERS),
        ("\\sqrt{x^2+9}", sp.Abs(x) + 3, ErrorType.ROOTS),
        ("\\frac{1}{2}+\\frac{1}{3}", sp.Rational(2, 5), ErrorType.FRACTIONS),
    ],
)
def test_expression_mutations_cover_typical_mistakes(
    text: str, wrong: Any, error: ErrorType
) -> None:
    matches = [
        kind for mutated, kind in expression_mutations(_raw(text)) if equivalent(mutated, wrong)
    ]
    assert matches
    assert matches[0] is error


def test_equation_mutations_detect_sign_transfer() -> None:
    statement = parse_line("5x - 3 = 2x + 9")
    assert isinstance(statement, Equation)
    student = 5 * x - 2 * x - (9 - 3)
    matches = [
        kind
        for candidate, kind in equation_mutations(statement.raw_lhs, statement.raw_rhs)
        if proportional(student, candidate, x)
    ]
    assert matches[0] is ErrorType.SIGN
