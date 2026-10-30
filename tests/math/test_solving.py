from typing import Any

import pytest
import sympy as sp

from yasno.math.parsing import Op
from yasno.math.solving import (
    Unsupported,
    contains,
    same_set,
    set_latex,
    solve_equation,
    solve_inequality,
    solve_system,
    subset,
)

x = sp.Symbol("x", real=True)
y = sp.Symbol("y", real=True)


@pytest.mark.parametrize(
    ("lhs", "rhs", "expected"),
    [
        (x**2 - 5 * x + 6, sp.Integer(0), sp.FiniteSet(2, 3)),
        (x / (x - 2), 2 / (x - 2), sp.EmptySet),
        ((x**2 - 4) / (x - 2), sp.Integer(0), sp.FiniteSet(-2)),
        (sp.sqrt(x + 2), x, sp.FiniteSet(2)),
        (2 ** (x + 1), sp.Integer(8), sp.FiniteSet(2)),
        (sp.log(x, 2) + sp.log(x - 2, 2), sp.Integer(3), sp.FiniteSet(4)),
        (sp.log(2 * x - 1, 5), sp.log(x + 1, 5), sp.FiniteSet(2)),
        (sp.log(x, 10) ** 2 - 3 * sp.log(x, 10) + 2, sp.Integer(0), sp.FiniteSet(10, 100)),
        (2 * (x + 1), 2 * x + 2, sp.Reals),
        (x**2 + 1, sp.Integer(0), sp.EmptySet),
    ],
)
def test_solve_equation(lhs: Any, rhs: Any, expected: Any) -> None:
    assert same_set(solve_equation(lhs, rhs, x), expected)


@pytest.mark.parametrize(
    ("parts", "ops", "expected"),
    [
        ((x**2 - 5 * x + 6, sp.Integer(0)), (Op.LT,), sp.Interval.open(2, 3)),
        (
            ((x - 1) / (x + 2), sp.Integer(0)),
            (Op.GE,),
            sp.Union(sp.Interval.open(-sp.oo, -2), sp.Interval(1, sp.oo)),
        ),
        ((sp.Integer(1), 2 * x - 3, sp.Integer(5)), (Op.LT, Op.LT), sp.Interval.open(2, 4)),
        ((sp.log(x, 2), sp.Integer(3)), (Op.LT,), sp.Interval.open(0, 8)),
        ((-2 * x + 4, sp.Integer(0)), (Op.GT,), sp.Interval.open(-sp.oo, 2)),
    ],
)
def test_solve_inequality(parts: tuple[Any, ...], ops: tuple[Op, ...], expected: Any) -> None:
    assert same_set(solve_inequality(parts, ops, x), expected)


def test_solve_system() -> None:
    assert solve_system([(x + y, sp.Integer(5)), (x - y, sp.Integer(1))], [x, y]) == [(3, 2)]


def test_unsupported_inputs() -> None:
    with pytest.raises(Unsupported):
        solve_equation(sp.sin(x), sp.Integer(0), x)
    with pytest.raises(Unsupported):
        solve_equation(x**40 - 1, sp.Integer(0), x)


def test_set_helpers() -> None:
    closed = sp.Union(sp.Interval.open(-sp.oo, 3), sp.FiniteSet(3))
    assert same_set(sp.Interval(-sp.oo, 3), closed)
    assert not same_set(sp.Interval(-sp.oo, 3), sp.Interval.open(-sp.oo, 3))
    assert subset(sp.FiniteSet(2), sp.FiniteSet(2, 3))
    assert not subset(sp.FiniteSet(2, 4), sp.FiniteSet(2, 3))
    assert contains(sp.Interval.Ropen(1, 2), sp.Integer(1))
    assert not contains(sp.Interval.Ropen(1, 2), sp.Integer(2))
    assert set_latex(sp.Union(sp.Interval(5, sp.oo), sp.Interval(-sp.oo, 3))) == (
        r"(-\infty; 3] \cup [5; +\infty)"
    )
    assert set_latex(sp.FiniteSet(3, 2)) == r"\{2; 3\}"
