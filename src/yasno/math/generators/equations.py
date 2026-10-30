import random

import sympy as sp

from yasno.math.errors import ErrorType
from yasno.math.generators.base import (
    Draft,
    X,
    Y,
    linear_latex,
    nonzero,
    number,
    point,
    poly_latex,
    require,
    roots,
    span,
)

SOLVE = "Реши уравнение"


def _solved(lhs: sp.Expr, rhs: sp.Expr) -> sp.Set:
    return sp.solveset(sp.Eq(lhs, rhs), X, sp.Reals)


def linear(rng: random.Random, difficulty: int) -> Draft:
    root = nonzero(rng, -span(difficulty), span(difficulty))
    if difficulty > 1 and rng.random() < 0.4:
        a = rng.randint(2, 5)
        p = nonzero(rng, -span(difficulty), span(difficulty))
        q = a * (root + p)
        prompt = f"{a}(x {'+' if p > 0 else '-'} {abs(p)}) = {q}"
        require(_solved(a * (X + p), sp.Integer(q)) == sp.FiniteSet(root))
        draft = Draft(SOLVE, prompt, roots(root))
        draft.add(roots(sp.Rational(q - p, a)), ErrorType.DISTRIBUTION)
        draft.add(roots(sp.Rational(q + a * p, a)), ErrorType.SIGN)
        draft.add(roots(sp.Rational(q, a) + p), ErrorType.SIGN)
        draft.add(roots(q - a * p - a), ErrorType.ARITHMETIC)
        return draft
    a = nonzero(rng, -span(difficulty), span(difficulty))
    c = nonzero(rng, -span(difficulty), span(difficulty))
    require(a != c)
    b = nonzero(rng, -2 * span(difficulty), 2 * span(difficulty))
    d = (a - c) * root + b
    prompt = f"{linear_latex(a, b)} = {linear_latex(c, d)}"
    require(_solved(a * X + b, c * X + d) == sp.FiniteSet(root))
    draft = Draft(SOLVE, prompt, roots(root))
    draft.add(roots(sp.Rational(d + b, a - c)), ErrorType.SIGN)
    if a + c != 0:
        draft.add(roots(sp.Rational(d - b, a + c)), ErrorType.SIGN)
    draft.add(roots(-root), ErrorType.SIGN)
    draft.add(roots((d - b) * (a - c)), ErrorType.ARITHMETIC)
    draft.add(roots(sp.Rational(a - c, d - b) if d != b else root + 1), ErrorType.ARITHMETIC)
    return draft


def quadratic(rng: random.Random, difficulty: int) -> Draft:
    form = rng.choice(["full", "full", "zero", "square"])
    if form == "zero":
        k = nonzero(rng, -span(difficulty), span(difficulty))
        a = rng.randint(1, difficulty)
        prompt = f"{poly_latex(a * X**2)} = {poly_latex(a * k * X)}"
        require(_solved(a * X**2, a * k * X) == sp.FiniteSet(0, k))
        draft = Draft(SOLVE, prompt, roots(0, k))
        draft.add(roots(k), ErrorType.DIVISION_BY_VARIABLE)
        draft.add(roots(0, -k), ErrorType.SIGN)
        draft.add(roots(-k), ErrorType.SIGN)
        draft.add(roots(0, a * k + 1), ErrorType.ARITHMETIC)
        return draft
    if form == "square":
        n = rng.randint(2, span(difficulty))
        prompt = f"x^{{2}} - {n * n} = 0"
        draft = Draft(SOLVE, prompt, roots(-n, n))
        draft.add(roots(n), ErrorType.LOST_ROOT)
        draft.add(roots(-n * n, n * n), ErrorType.ROOTS)
        draft.add(roots(-2 * n, 2 * n), ErrorType.ARITHMETIC)
        draft.add(roots(-n), ErrorType.LOST_ROOT)
        return draft
    p, q = rng.sample([v for v in range(-span(difficulty), span(difficulty) + 1) if v], 2)
    a = 1 if difficulty == 1 else rng.choice([1, 1, 2, -1, 3])
    expr = sp.expand(a * (X - p) * (X - q))
    prompt = f"{poly_latex(expr)} = 0"
    require(_solved(expr, sp.Integer(0)) == sp.FiniteSet(p, q))
    draft = Draft(SOLVE, prompt, roots(p, q))
    poly = sp.Poly(expr, X)
    ca, cb, cc = (int(value) for value in poly.all_coeffs())
    draft.add(roots(-p, -q), ErrorType.SIGN)
    draft.add(roots(2 * a * p, 2 * a * q), ErrorType.FORMULA)
    wrong = cb * cb + 4 * ca * cc
    if wrong >= 0 and sp.sqrt(wrong).is_Rational:
        root = sp.sqrt(wrong)
        draft.add(
            roots(sp.Rational(-cb + root, 2 * ca), sp.Rational(-cb - root, 2 * ca)),
            ErrorType.FORMULA,
        )
    draft.add(roots(p), ErrorType.LOST_ROOT)
    draft.add(roots(p + 1, q - 1), ErrorType.ARITHMETIC)
    return draft


def rational(rng: random.Random, difficulty: int) -> Draft:
    if difficulty == 1 or rng.random() < 0.5:
        p, q = rng.sample([v for v in range(-span(difficulty), span(difficulty) + 1) if v], 2)
        numerator = sp.expand((X - p) * (X - q))
        prompt = rf"\frac{{{poly_latex(numerator)}}}{{x {'-' if p > 0 else '+'} {abs(p)}}} = 0"
        require(_solved(numerator / (X - p), sp.Integer(0)) == sp.FiniteSet(q))
        draft = Draft(SOLVE, prompt, roots(q))
        draft.add(roots(p, q), ErrorType.DOMAIN)
        draft.add(roots(-q), ErrorType.SIGN)
        draft.add(roots(-p, -q), ErrorType.SIGN)
        draft.add(roots(p), ErrorType.DOMAIN)
        return draft
    root = nonzero(rng, -span(difficulty), span(difficulty))
    p, q = rng.sample([v for v in range(-span(difficulty), span(difficulty) + 1) if v != root], 2)
    a = root - q
    b = root - p
    require(a != b and a != 0 and b != 0)
    prompt = (
        rf"\frac{{{a}}}{{x {'-' if p > 0 else '+'} {abs(p)}}} = "
        rf"\frac{{{b}}}{{x {'-' if q > 0 else '+'} {abs(q)}}}"
    )
    require(_solved(a / (X - p), b / (X - q)) == sp.FiniteSet(root))
    draft = Draft(SOLVE, prompt, roots(root))
    draft.add(
        roots(sp.Rational(a * q + b * p, a + b)) if a + b else roots(root + 1), ErrorType.SIGN
    )
    draft.add(roots(sp.Rational(a * p - b * q, a - b)), ErrorType.FRACTIONS)
    draft.add(roots(-root), ErrorType.SIGN)
    draft.add(roots(root, p), ErrorType.DOMAIN)
    return draft


def systems(rng: random.Random, difficulty: int) -> Draft:
    x0 = nonzero(rng, -span(difficulty), span(difficulty))
    y0 = nonzero(rng, -span(difficulty), span(difficulty))
    require(x0 != y0)
    if difficulty == 1:
        a1, b1, a2, b2 = 1, 1, 1, -1
    else:
        a1, b1 = rng.randint(1, 3), nonzero(rng, -3, 3)
        a2, b2 = nonzero(rng, -3, 3), nonzero(rng, -3, 3)
        require(a1 * b2 - a2 * b1 != 0)
    c1, c2 = a1 * x0 + b1 * y0, a2 * x0 + b2 * y0
    first = f"{linear_latex(a1, 0)} {'+' if b1 > 0 else '-'} {linear_latex(abs(b1), 0, 'y')}"
    second = f"{linear_latex(a2, 0)} {'+' if b2 > 0 else '-'} {linear_latex(abs(b2), 0, 'y')}"
    prompt = rf"\begin{{cases}} {first} = {c1} \\ {second} = {c2} \end{{cases}}"
    solved = sp.solve([a1 * X + b1 * Y - c1, a2 * X + b2 * Y - c2], [X, Y], dict=True)
    require(solved == [{X: x0, Y: y0}])
    draft = Draft("Реши систему уравнений", prompt, point(x0, y0))
    draft.add(point(y0, x0), ErrorType.OTHER)
    draft.add(point(x0, -y0), ErrorType.SIGN)
    draft.add(point(-x0, -y0), ErrorType.SIGN)
    wrong = sp.solve([a1 * X + b1 * Y - c1, a2 * X + b2 * Y + c2], [X, Y], dict=True)
    if wrong:
        draft.add(point(wrong[0][X], wrong[0][Y]), ErrorType.SIGN)
    draft.add(point(x0 + 1, y0 - 1), ErrorType.ARITHMETIC)
    return draft


def exponential(rng: random.Random, difficulty: int) -> Draft:
    base = rng.choice([2, 3, 5] if difficulty > 1 else [2, 3])
    k = rng.choice([1, 1, 2] if difficulty > 1 else [1])
    m = nonzero(rng, -4, 4)
    n = rng.randint(1 if base > 2 else 2, 4 if base == 2 else 3)
    require((n - m) % k == 0)
    root = (n - m) // k
    exponent = linear_latex(k, m)
    prompt = rf"{base}^{{{exponent}}} = {base**n}"
    require(_solved(sp.Integer(base) ** (k * X + m), sp.Integer(base**n)) == sp.FiniteSet(root))
    draft = Draft(SOLVE, prompt, roots(root))
    draft.add(roots(sp.Rational(n + m, k)), ErrorType.SIGN)
    draft.add(roots(sp.Rational(base**n - m, k)), ErrorType.POWERS)
    draft.add(roots(sp.Rational(base**n, base) - m), ErrorType.POWERS)
    draft.add(roots((n - m) * k + 1 if k == 1 else (n - m) * k), ErrorType.ARITHMETIC)
    return draft


def logarithms(rng: random.Random, difficulty: int) -> Draft:
    base = rng.choice([2, 3, 5])
    n = rng.randint(1, 4 if base == 2 else 3)
    if difficulty == 1 and rng.random() < 0.5:
        prompt = rf"\log_{{{base}}} {base**n}"
        draft = Draft("Вычисли", prompt, number(n))
        draft.add(number(sp.Rational(base**n, base)), ErrorType.FORMULA)
        draft.add(number(n + 1), ErrorType.ARITHMETIC)
        draft.add(number(sp.Rational(1, n)), ErrorType.FORMULA)
        draft.add(number(base * n), ErrorType.FORMULA)
        return draft
    m = nonzero(rng, -5, 5)
    root = base**n - m
    prompt = rf"\log_{{{base}}}\left({linear_latex(1, m)}\right) = {n}"
    require(_solved(sp.log(X + m, base), sp.Integer(n)) == sp.FiniteSet(root))
    draft = Draft(SOLVE, prompt, roots(root))
    draft.add(roots(base * n - m), ErrorType.FORMULA)
    draft.add(roots(n**base - m), ErrorType.FORMULA)
    draft.add(roots(base**n + m), ErrorType.SIGN)
    draft.add(roots(base ** (n + 1) - m), ErrorType.ARITHMETIC)
    return draft
