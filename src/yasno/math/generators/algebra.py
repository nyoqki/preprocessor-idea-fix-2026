import random

import sympy as sp

from yasno.math.errors import ErrorType
from yasno.math.generators.base import (
    Draft,
    Rejected,
    X,
    expression,
    nonzero,
    number,
    require,
    signed,
    span,
)
from yasno.math.mistakes import expression_mutations
from yasno.math.parsing import Expression, parse_line


def _binomial(sign: int, value: int) -> str:
    return f"(x {'+' if sign > 0 else '-'} {value})"


def expressions(rng: random.Random, difficulty: int) -> Draft:
    a = rng.randint(1, span(difficulty))
    b = rng.randint(1, span(difficulty))
    c = nonzero(rng, -span(difficulty), span(difficulty))
    first_sign, second_sign = rng.choice([1, -1]), rng.choice([1, -1])
    form = rng.choice(
        ["square-linear", "square-difference"] if difficulty > 1 else ["square-linear"]
    )
    if form == "square-linear":
        coefficient = f"{signed(c)}" if abs(c) != 1 else ("+" if c > 0 else "-")
        prompt = f"{_binomial(first_sign, a)}^{{2}} {coefficient}{_binomial(second_sign, b)}"
    else:
        prompt = f"{_binomial(first_sign, a)}^{{2}} - (x - {b})(x + {b})"
    statement = parse_line(prompt)
    if not isinstance(statement, Expression):
        raise Rejected
    correct = sp.expand(statement.expr)
    draft = Draft("Раскрой скобки и приведи подобные слагаемые", prompt, expression(correct))
    for mutated, error in expression_mutations(statement.raw):
        draft.add(expression(sp.expand(mutated)), error)
    leading, rest = correct.as_coefficients_dict()[X], correct.as_coefficients_dict()[sp.Integer(1)]
    draft.add(expression(correct - leading * X + (leading + 1) * X), ErrorType.ARITHMETIC)
    draft.add(expression(correct - rest + (rest - 1)), ErrorType.ARITHMETIC)
    return draft


def factoring(rng: random.Random, difficulty: int) -> Draft:
    form = rng.choice(["trinomial", "squares", "common"])
    if form == "trinomial":
        p, q = rng.sample([n for n in range(-span(difficulty), span(difficulty) + 1) if n], 2)
        prompt = str(sp.latex(sp.expand((X + p) * (X + q))))
        draft = Draft("Разложи на множители", prompt, expression((X + p) * (X + q)))
        draft.add(expression((X - p) * (X - q)), ErrorType.SIGN)
        draft.add(expression((X + p) * (X - q)), ErrorType.SIGN)
        draft.add(expression((X - p) * (X + q)), ErrorType.SIGN)
        draft.add(expression((X + p + q) * (X + p * q)), ErrorType.FORMULA)
        return draft
    if form == "squares":
        k = rng.randint(1, 2 if difficulty == 1 else 3)
        a = rng.randint(1, span(difficulty))
        prompt = str(sp.latex(k * k * X**2 - a * a))
        correct = (k * X - a) * (k * X + a)
        draft = Draft("Разложи на множители", prompt, expression(correct))
        draft.add(expression((k * X - a) ** 2), ErrorType.FORMULA)
        draft.add(expression((k * X + a) ** 2), ErrorType.FORMULA)
        draft.add(expression((k * X - a * a) * (k * X + a * a)), ErrorType.POWERS)
        draft.add(expression((k * k * X - a) * (X + a)), ErrorType.FORMULA)
        return draft
    k = rng.randint(2, 3 + difficulty)
    m = nonzero(rng, -span(difficulty), span(difficulty))
    prompt = str(sp.latex(sp.expand(k * X * (X + m))))
    correct = k * X * (X + m)
    draft = Draft("Разложи на множители", prompt, expression(correct))
    draft.add(expression(k * X * (X + k * m)), ErrorType.ARITHMETIC)
    draft.add(expression(k * X * (X - m)), ErrorType.SIGN)
    draft.add(expression(k * (X + m)), ErrorType.POWERS)
    draft.add(expression(X * (k * X + m)), ErrorType.DISTRIBUTION)
    return draft


def progressions(rng: random.Random, difficulty: int) -> Draft:
    n = rng.randint(5, 6 + 3 * difficulty)
    if rng.random() < 0.6:
        first = nonzero(rng, -span(difficulty), span(difficulty))
        step = nonzero(rng, -5, 5 + difficulty)
        prompt = rf"a_{{1}} = {first},\ d = {step},\ a_{{{n}}} = \,?"
        correct = first + (n - 1) * step
        draft = Draft("Найди член арифметической прогрессии", prompt, number(correct))
        draft.add(number(first + n * step), ErrorType.FORMULA)
        draft.add(number(first - (n - 1) * step), ErrorType.SIGN)
        draft.add(number(first * (n - 1) * step), ErrorType.FORMULA)
        draft.add(number(first + (n - 1) + step), ErrorType.ARITHMETIC)
        return draft
    first = nonzero(rng, -4, 4)
    ratio = rng.choice([2, 3, -2] if difficulty > 1 else [2, 3])
    n = rng.randint(4, 5 + difficulty)
    require(abs(first * ratio ** (n - 1)) < 10**5)
    prompt = rf"b_{{1}} = {first},\ q = {ratio},\ b_{{{n}}} = \,?"
    correct = first * ratio ** (n - 1)
    draft = Draft("Найди член геометрической прогрессии", prompt, number(correct))
    draft.add(number(first * ratio**n), ErrorType.FORMULA)
    draft.add(number(first * ratio * (n - 1)), ErrorType.FORMULA)
    draft.add(number((first * ratio) ** (n - 1)), ErrorType.POWERS)
    draft.add(number(first + ratio ** (n - 1)), ErrorType.ARITHMETIC)
    return draft
