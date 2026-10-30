import cmath
import random
from typing import Any

import sympy as sp

from yasno.math.limits import limited

SAMPLE_POINTS = 7
RELATIVE_TOLERANCE = 1e-8


def evaluate_tree(tree: Any) -> Any:
    if tree.is_Atom:
        return tree
    return tree.func(*[evaluate_tree(arg) for arg in tree.args])


def _needs_positive(expr: Any) -> bool:
    for power in expr.atoms(sp.Pow):
        exponent = power.exp
        if exponent.is_Rational and not exponent.is_Integer:
            return True
    return bool(expr.has(sp.log))


def _value(expr: Any, substitution: dict[Any, Any]) -> complex | None:
    try:
        result = complex(expr.xreplace(substitution).evalf(20))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None
    if not (cmath.isfinite(result)):
        return None
    return result


def _points(symbols: list[Any], positive: bool, seed: int) -> list[dict[Any, Any]]:
    rng = random.Random(seed)
    points = []
    for _ in range(SAMPLE_POINTS):
        point = {}
        for symbol in symbols:
            magnitude = sp.Rational(rng.randint(130, 3700), 1000)
            sign = 1 if positive or rng.random() < 0.6 else -1
            point[symbol] = sign * magnitude
        points.append(point)
    return points


def numerically_equal(first: Any, second: Any) -> bool | None:
    symbols = sorted(first.free_symbols | second.free_symbols, key=str)
    positive = _needs_positive(first) or _needs_positive(second)
    seed = sum(ord(char) for char in "".join(str(symbol) for symbol in symbols)) + 17
    compared = 0
    for point in _points(symbols, positive, seed):
        a = _value(first, point)
        b = _value(second, point)
        if a is None or b is None:
            continue
        if positive and (abs(a.imag) > 1e-9 or abs(b.imag) > 1e-9):
            continue
        if abs(a - b) > RELATIVE_TOLERANCE * (1 + abs(a) + abs(b)):
            return False
        compared += 1
    if compared < 2:
        return None
    return True


def equivalent(first: Any, second: Any) -> bool | None:
    if first == second:
        return True
    difference = first - second

    def symbolic() -> bool:
        return bool(sp.expand(difference) == 0) or bool(sp.cancel(sp.together(difference)) == 0)

    if limited(symbolic, 0.4, False):
        return True
    return limited(lambda: numerically_equal(first, second), 0.6, None)


def proportional(first: Any, second: Any, variable: Any) -> bool:
    if first == 0 or second == 0:
        return False

    def ratio_is_constant() -> bool:
        ratio = sp.cancel(sp.together(first / second))
        return bool(not ratio.has(variable) and ratio != 0 and ratio.is_finite is not False)

    return bool(limited(ratio_is_constant, 0.4, False))


def simplified(expr: Any) -> Any:
    def work() -> Any:
        expanded = sp.expand(expr)
        if expanded.is_polynomial():
            return expanded
        return sp.simplify(expr)

    return limited(work, 0.6, expr)


def to_latex(expr: Any) -> str:
    return str(sp.latex(expr))
