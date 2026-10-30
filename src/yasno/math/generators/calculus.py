import random

import sympy as sp

from yasno.math.errors import ErrorType
from yasno.math.generators.base import Draft, X, expression, nonzero, require


def _power_term(coefficient: int, exponent: int) -> sp.Expr:
    return sp.Integer(coefficient) * X**exponent


def derivative(rng: random.Random, difficulty: int) -> Draft:
    n, m = sorted(rng.sample(range(2, 4 + difficulty), 2), reverse=True)
    a = nonzero(rng, -5, 5)
    b = nonzero(rng, -5, 5)
    c = nonzero(rng, -9, 9)
    function = _power_term(a, n) + _power_term(b, m) + c
    trig = difficulty > 1 and rng.random() < 0.5
    if trig:
        k = nonzero(rng, -4, 4)
        function = _power_term(a, n) + k * sp.cos(X) + c
    correct = sp.diff(function, X)
    prompt = f"f(x) = {sp.latex(function)}"
    draft = Draft("Найди производную функции", prompt, expression(correct))
    terms = function.as_ordered_terms()
    lowered = sum(
        (term / X if term.has(X) and term.is_polynomial(X) else sp.diff(term, X))
        for term in terms
        if term.has(X)
    )
    draft.add(expression(lowered), ErrorType.FORMULA)
    raised = sum(
        (sp.diff(term, X) * X**2 if term.is_polynomial(X) else sp.diff(term, X))
        for term in terms
        if term.has(X)
    )
    draft.add(expression(raised), ErrorType.FORMULA)
    draft.add(expression(correct + c), ErrorType.FORMULA)
    if trig:
        draft.add(expression(correct.subs(sp.sin(X), -sp.sin(X))), ErrorType.SIGN)
    else:
        draft.add(expression(correct - 2 * sp.diff(_power_term(b, m), X)), ErrorType.SIGN)
    draft.add(expression(correct + X ** (n - 1)), ErrorType.ARITHMETIC)
    require(correct != 0)
    return draft
