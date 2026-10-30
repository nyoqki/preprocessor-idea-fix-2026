import random

import sympy as sp

from yasno.math.errors import ErrorType
from yasno.math.generators.base import (
    Draft,
    X,
    linear_latex,
    nonzero,
    poly_latex,
    require,
    solution_set,
    span,
)
from yasno.math.parsing import FLIPPED, Op, relational

SOLVE = "Реши неравенство"
_STRICT = {Op.LT: Op.LE, Op.LE: Op.LT, Op.GT: Op.GE, Op.GE: Op.GT}
_LATEX = {Op.LT: "<", Op.LE: r"\le", Op.GT: ">", Op.GE: r"\ge"}


def _solve(expr: sp.Expr, op: Op) -> sp.Set:
    return sp.solveset(relational(expr, op, 0), X, sp.Reals)


def linear(rng: random.Random, difficulty: int) -> Draft:
    root = nonzero(rng, -span(difficulty), span(difficulty))
    k = nonzero(rng, -span(difficulty), span(difficulty))
    if rng.random() < 0.6:
        k = -abs(k)
    c = rng.randint(-3, 3) if difficulty > 1 else 0
    a = k + c
    b = nonzero(rng, -2 * span(difficulty), 2 * span(difficulty))
    d = k * root + b
    op = rng.choice(list(_LATEX))
    prompt = f"{linear_latex(a, b)} {_LATEX[op]} {linear_latex(c, d)}"
    correct = _solve(a * X + b - c * X - d, op)
    require(correct.boundary == sp.FiniteSet(root))
    draft = Draft(SOLVE, prompt, solution_set(correct))
    draft.add(solution_set(_solve(-(a * X + b - c * X - d), op)), ErrorType.INEQUALITY_FLIP)
    draft.add(solution_set(_solve(k * X - (d + b), op)), ErrorType.SIGN)
    draft.add(solution_set(_solve(a * X + b - c * X - d, _STRICT[op])), ErrorType.OTHER)
    draft.add(solution_set(_solve(a * X + b - c * X - d - k, op)), ErrorType.ARITHMETIC)
    return draft


def quadratic(rng: random.Random, difficulty: int) -> Draft:
    p, q = sorted(rng.sample(range(-span(difficulty), span(difficulty) + 1), 2))
    a = 1 if difficulty == 1 else rng.choice([1, 1, -1, 2])
    expr = sp.expand(a * (X - p) * (X - q))
    op = rng.choice(list(_LATEX))
    prompt = f"{poly_latex(expr)} {_LATEX[op]} 0"
    correct = _solve(expr, op)
    draft = Draft(SOLVE, prompt, solution_set(correct))
    draft.add(solution_set(_solve(expr, FLIPPED[op])), ErrorType.SIGN)
    draft.add(solution_set(_solve(expr, _STRICT[op])), ErrorType.OTHER)
    draft.add(solution_set(_solve(sp.expand(a * (X + p) * (X + q)), op)), ErrorType.SIGN)
    draft.add(
        solution_set(relational(X, op if a > 0 else FLIPPED[op], q).as_set()), ErrorType.LOST_ROOT
    )
    draft.add(
        solution_set(_solve(sp.expand(a * (X - p + 1) * (X - q - 1)), op)), ErrorType.ARITHMETIC
    )
    return draft
