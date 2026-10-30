import math
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Any

import sympy as sp
from sympy.calculus.util import continuous_domain

from yasno.math.limits import MAX_DEGREE, MathTimeout, limited, reraise_if_expired, time_limit
from yasno.math.parsing import Op, relational

TOLERANCE = 1e-9

type Piece = tuple[float, float, bool, bool]


class Unsupported(Exception):
    pass


def domain_of(expr: Any, variable: Any) -> Any:
    if not expr.has(variable):
        return sp.Reals
    found = limited(lambda: continuous_domain(expr, variable, sp.Reals), 0.6, None)
    if found is None or not isinstance(found, sp.Set):
        return sp.Reals
    return found


def joint_domain(exprs: Sequence[Any], variable: Any) -> Any:
    result: Any = sp.Reals
    for expr in exprs:
        result = result.intersect(domain_of(expr, variable))
    return result


def _is_real_number(value: Any) -> bool:
    if not value.is_number:
        return False
    numeric = complex(value.evalf(20))
    return abs(numeric.imag) < TOLERANCE and math.isfinite(numeric.real)


def _check_size(expr: Any, variable: Any) -> None:
    numerator, _ = sp.fraction(sp.together(expr))
    if numerator.is_polynomial(variable):
        degree = sp.degree(numerator, variable) if numerator.has(variable) else 0
        if degree > MAX_DEGREE:
            raise Unsupported


def _evaluator(expr: Any, variable: Any) -> Callable[[float], float]:
    function = sp.lambdify(variable, expr, modules="math")

    def evaluate(point: float) -> float:
        try:
            value = function(point)
        except (ArithmeticError, ValueError, TypeError, OverflowError):
            return math.nan
        if isinstance(value, complex):
            return value.real if abs(value.imag) < TOLERANCE else math.nan
        return float(value)

    return evaluate


def _grid() -> list[float]:
    return [math.sinh(step / 250) for step in range(-2000, 2001)]


def _snap(value: float) -> Any:
    for candidate in (
        sp.nsimplify(value, tolerance=1e-10, rational=True),
        sp.nsimplify(value, [sp.sqrt(2), sp.sqrt(3), sp.sqrt(5)], tolerance=1e-10),
    ):
        if abs(float(candidate) - value) < 1e-9 and len(str(candidate)) < 30:
            return candidate
    return sp.Float(value, 15)


def numeric_roots(expr: Any, variable: Any, domain: Any) -> list[Any]:
    evaluate = _evaluator(expr, variable)
    points = _grid()
    values = [evaluate(point) for point in points]
    roots: list[float] = []
    for index, value in enumerate(values):
        if value == 0:
            roots.append(points[index])
    for left, right, f_left, f_right in zip(points, points[1:], values, values[1:], strict=False):
        if not (math.isfinite(f_left) and math.isfinite(f_right)) or f_left * f_right >= 0:
            continue
        low, high, f_low = left, right, f_left
        for _ in range(80):
            middle = (low + high) / 2
            f_middle = evaluate(middle)
            if not math.isfinite(f_middle):
                break
            if f_low * f_middle <= 0:
                high = middle
            else:
                low, f_low = middle, f_middle
        root = (low + high) / 2
        value = evaluate(root)
        if math.isfinite(value) and abs(value) < 1e-7 * (1 + abs(f_left) + abs(f_right)):
            roots.append(root)
    result: list[Any] = []
    for root in sorted(roots):
        if result and abs(float(result[-1]) - root) < 1e-7:
            continue
        snapped = _snap(root)
        if domain.contains(snapped) is not sp.false:
            result.append(snapped)
    return result


def _finite_real(result: Any) -> bool:
    return isinstance(result, sp.FiniteSet) and all(_is_real_number(item) for item in result)


def _clean(result: Any, domain: Any) -> Any:
    if result is sp.EmptySet:
        return result
    if _finite_real(result):
        kept = [item for item in result if domain.contains(item) is not sp.false]
        return sp.FiniteSet(*kept)
    if (
        isinstance(result, sp.Interval | sp.Union | sp.Complement | sp.Intersection)
        and _pieces(result) is not None
    ):
        return result
    raise Unsupported


def solve_equation(lhs: Any, rhs: Any, variable: Any) -> Any:
    expr = lhs - rhs
    symbols = expr.free_symbols
    if not symbols:
        zero = limited(lambda: sp.simplify(expr) == 0, 0.5, None)
        if zero is None:
            raise Unsupported
        return sp.Reals if zero else sp.EmptySet
    if symbols != {variable}:
        raise Unsupported
    if expr.has(sp.sin, sp.cos, sp.tan, sp.cot):
        raise Unsupported
    _check_size(expr, variable)
    domain = joint_domain([lhs, rhs], variable)
    try:
        with time_limit(1.0):
            result = sp.solveset(expr, variable, domain)
        return _clean(result, domain)
    except (MathTimeout, Unsupported, NotImplementedError, ValueError, TypeError):
        reraise_if_expired()
    try:
        with time_limit(0.8):
            return sp.FiniteSet(*numeric_roots(expr, variable, domain))
    except MathTimeout as exc:
        reraise_if_expired()
        raise Unsupported from exc


def _sign_method(expr: Any, op: Op, variable: Any, domain: Any) -> Any:
    evaluate = _evaluator(expr, variable)
    zeros = [float(root) for root in numeric_roots(expr, variable, sp.Reals)]
    boundary = limited(lambda: domain.boundary, 0.3, sp.EmptySet)
    edges = (
        [float(point) for point in boundary if _is_real_number(point)]
        if _finite_real(boundary)
        else []
    )
    critical = sorted({*zeros, *edges})
    probes = [critical[0] - 1.0] if critical else [0.0]
    probes += [(a + b) / 2 for a, b in pairwise(critical)]
    if critical:
        probes.append(critical[-1] + 1.0)

    def holds(point: float) -> bool:
        value = evaluate(point)
        if not math.isfinite(value):
            return False
        match op:
            case Op.LT:
                return value < -TOLERANCE
            case Op.LE:
                return value < TOLERANCE
            case Op.GT:
                return value > TOLERANCE
            case _:
                return value > -TOLERANCE

    exact = sorted({_snap(point) for point in critical}, key=float)
    bounds = [-sp.oo, *exact, sp.oo]
    result: Any = sp.EmptySet
    for index, probe in enumerate(probes):
        if holds(probe):
            result = result.union(sp.Interval.open(bounds[index], bounds[index + 1]))
    for point, value in zip(exact, critical, strict=True):
        if holds(value) and domain.contains(point) is not sp.false:
            result = result.union(sp.FiniteSet(point))
    return result.intersect(domain)


def _constant_truth(expr: Any, op: Op) -> bool:
    statement = relational(expr, op, 0)
    truth: bool | None = limited(lambda: bool(sp.simplify(statement)), 0.5, None)
    if truth is None:
        raise Unsupported
    return truth


def _solve_relation(left: Any, op: Op, right: Any, variable: Any, domain: Any) -> Any:
    expr = left - right
    if op is Op.NE:
        return domain - solve_equation(left, right, variable)
    if expr.has(sp.sin, sp.cos, sp.tan, sp.cot):
        raise Unsupported
    _check_size(expr, variable)
    if not expr.free_symbols:
        return domain if _constant_truth(expr, op) else sp.EmptySet
    try:
        with time_limit(1.0):
            return _clean(sp.solveset(relational(left, op, right), variable, domain), domain)
    except (MathTimeout, Unsupported, NotImplementedError, ValueError, TypeError):
        reraise_if_expired()
    try:
        with time_limit(0.8):
            return _sign_method(expr, op, variable, domain)
    except MathTimeout as exc:
        reraise_if_expired()
        raise Unsupported from exc


def solve_inequality(parts: Sequence[Any], ops: Sequence[Op], variable: Any) -> Any:
    symbols: set[Any] = set()
    for part in parts:
        symbols |= part.free_symbols
    if symbols - {variable}:
        raise Unsupported
    domain = joint_domain(parts, variable)
    result: Any = domain
    for left, op, right in zip(parts, ops, parts[1:], strict=False):
        result = result.intersect(_solve_relation(left, op, right, variable, domain))
    return result


def solve_system(equations: Sequence[tuple[Any, Any]], variables: Sequence[Any]) -> Any:
    exprs = [lhs - rhs for lhs, rhs in equations]
    for expr in exprs:
        _check_size(expr, variables[0])
        if not all(expr.is_polynomial(variable) for variable in variables):
            raise Unsupported
    try:
        with time_limit(1.2):
            solutions = sp.solve(exprs, list(variables), dict=True)
    except (MathTimeout, NotImplementedError, ValueError, TypeError) as exc:
        reraise_if_expired()
        raise Unsupported from exc
    points = []
    for solution in solutions:
        if len(solution) != len(variables):
            raise Unsupported
        point = tuple(solution[variable] for variable in variables)
        if all(_is_real_number(value) for value in point):
            points.append(point)
    return points


def _float(value: Any) -> float:
    if value == sp.oo:
        return math.inf
    if value == -sp.oo:
        return -math.inf
    return float(sp.N(value, 20))


def _pieces(value: Any) -> list[Piece] | None:
    if value is sp.EmptySet:
        return []
    if value == sp.Reals:
        return [(-math.inf, math.inf, False, False)]
    if isinstance(value, sp.FiniteSet):
        if not all(_is_real_number(item) for item in value):
            return None
        return _merge([(_float(item), _float(item), True, True) for item in value])
    if isinstance(value, sp.Interval):
        return [
            (
                _float(value.start),
                _float(value.end),
                not value.left_open,
                not value.right_open,
            )
        ]
    if isinstance(value, sp.Union):
        collected: list[Piece] = []
        for arg in value.args:
            pieces = _pieces(arg)
            if pieces is None:
                return None
            collected.extend(pieces)
        return _merge(collected)
    if isinstance(value, sp.Complement | sp.Intersection):
        simplified = limited(lambda: value.doit(), 0.3, None)
        if simplified is None or simplified == value:
            return None
        return _pieces(simplified)
    return None


def _close(a: float, b: float) -> bool:
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= TOLERANCE * (1 + abs(a))


def _overlaps(first: Piece, second: Piece) -> bool:
    if _close(second[0], first[1]):
        return first[3] or second[2]
    return second[0] < first[1]


def _join(first: Piece, second: Piece) -> Piece:
    low_closed = first[2] or second[2] if _close(first[0], second[0]) else first[2]
    if _close(first[1], second[1]):
        return (first[0], first[1], low_closed, first[3] or second[3])
    if second[1] > first[1]:
        return (first[0], second[1], low_closed, second[3])
    return (first[0], first[1], low_closed, first[3])


def _merge(pieces: list[Piece]) -> list[Piece]:
    ordered = sorted(pieces, key=lambda piece: (piece[0], not piece[2]))
    merged: list[Piece] = []
    for piece in ordered:
        if merged and _overlaps(merged[-1], piece):
            merged[-1] = _join(merged[-1], piece)
        else:
            merged.append(piece)
    return merged


def _piece_equal(a: Piece, b: Piece) -> bool:
    return (
        _close(a[0], b[0])
        and _close(a[1], b[1])
        and (math.isinf(a[0]) or a[2] == b[2])
        and (math.isinf(a[1]) or a[3] == b[3])
    )


def same_set(first: Any, second: Any) -> bool | None:
    a = _pieces(first)
    b = _pieces(second)
    if a is None or b is None:
        return None
    return len(a) == len(b) and all(_piece_equal(x, y) for x, y in zip(a, b, strict=True))


def _bound_ok(near: float, far: float, near_closed: bool, far_closed: bool) -> bool:
    if _close(near, far):
        return far_closed or not near_closed
    return True


def _piece_inside(inner: Piece, outer: Piece) -> bool:
    if inner[0] < outer[0] and not _close(inner[0], outer[0]):
        return False
    if inner[1] > outer[1] and not _close(inner[1], outer[1]):
        return False
    return _bound_ok(inner[0], outer[0], inner[2], outer[2]) and _bound_ok(
        inner[1], outer[1], inner[3], outer[3]
    )


def subset(first: Any, second: Any) -> bool | None:
    a = _pieces(first)
    b = _pieces(second)
    if a is None or b is None:
        return None
    return all(any(_piece_inside(piece, outer) for outer in b) for piece in a)


def contains(values: Any, point: Any) -> bool:
    pieces = _pieces(values)
    if pieces is None or not _is_real_number(point):
        return False
    target = _float(point)
    single: Piece = (target, target, True, True)
    return any(_piece_inside(single, piece) for piece in pieces)


def is_finite(values: Any) -> bool:
    return values is sp.EmptySet or _finite_real(values)


def finite_elements(values: Any) -> list[Any]:
    if values is sp.EmptySet:
        return []
    if _finite_real(values):
        return sorted(values, key=_float)
    return []


def restrict(values: Any, domain: Any) -> Any:
    if domain == sp.Reals:
        return values
    if is_finite(values):
        return sp.FiniteSet(*[item for item in finite_elements(values) if contains(domain, item)])
    result = limited(lambda: values.intersect(domain), 0.5, None)
    return values if result is None else result


def difference(first: Any, second: Any) -> Any:
    if is_finite(first):
        return sp.FiniteSet(
            *[item for item in finite_elements(first) if not contains(second, item)]
        )
    result = limited(lambda: first - second, 0.5, None)
    return sp.EmptySet if result is None else result


def number_latex(value: Any) -> str:
    return str(sp.latex(value))


def set_latex(values: Any) -> str:
    if values is sp.EmptySet:
        return r"\varnothing"
    if values == sp.Reals:
        return r"(-\infty; +\infty)"
    if is_finite(values):
        return r"\{" + "; ".join(number_latex(item) for item in finite_elements(values)) + r"\}"
    if isinstance(values, sp.Interval):
        start = r"-\infty" if values.start == -sp.oo else number_latex(values.start)
        end = r"+\infty" if values.end == sp.oo else number_latex(values.end)
        left = "(" if values.left_open or values.start == -sp.oo else "["
        right = ")" if values.right_open or values.end == sp.oo else "]"
        return f"{left}{start}; {end}{right}"
    if isinstance(values, sp.Union):
        ordered = sorted(values.args, key=lambda arg: _float(arg.inf))
        return r" \cup ".join(set_latex(arg) for arg in ordered)
    return str(sp.latex(values))


def answer_latex(values: Any, variable: Any) -> str:
    name = str(sp.latex(variable)) if variable is not None else "x"
    if values is sp.EmptySet:
        return r"\varnothing"
    if is_finite(values):
        return "; ".join(f"{name} = {number_latex(item)}" for item in finite_elements(values))
    return f"{name} \\in {set_latex(values)}"


def same_interior(first: Any, second: Any) -> bool | None:
    a = _pieces(first)
    b = _pieces(second)
    if a is None or b is None:
        return None
    open_a = [(low, high) for low, high, _, _ in a if not _close(low, high)]
    open_b = [(low, high) for low, high, _, _ in b if not _close(low, high)]
    return len(open_a) == len(open_b) and all(
        _close(x[0], y[0]) and _close(x[1], y[1]) for x, y in zip(open_a, open_b, strict=True)
    )


def critical_points(parts: Sequence[Any], variable: Any) -> Any:
    points: Any = sp.EmptySet
    for left, right in pairwise(parts):
        try:
            points = points.union(solve_equation(left, right, variable))
        except Unsupported:
            continue
    boundary = limited(lambda: joint_domain(parts, variable).boundary, 0.3, sp.EmptySet)
    if _finite_real(boundary):
        points = points.union(boundary)
    return points
