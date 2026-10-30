import random

import sympy as sp

from yasno.math.errors import ErrorType
from yasno.math.generators.base import (
    Draft,
    expression,
    nonzero,
    number,
    require,
)

A = sp.Symbol("a", positive=True)


def _fraction_latex(value: sp.Rational) -> str:
    return rf"\frac{{{value.p}}}{{{value.q}}}"


def fractions(rng: random.Random, difficulty: int) -> Draft:
    operations = ["+", "-"] if difficulty == 1 else ["+", "-", "*", ":"]
    operation = rng.choice(operations)
    top = 4 + 2 * difficulty
    b, d = rng.sample(range(2, top + 1), 2)
    a = rng.randint(1, b - 1)
    c = rng.randint(1, d - 1)
    first, second = sp.Rational(a, b), sp.Rational(c, d)
    require(first.q == b and second.q == d)
    symbol = {"+": "+", "-": "-", "*": r"\cdot", ":": ":"}[operation]
    prompt = f"{_fraction_latex(first)} {symbol} {_fraction_latex(second)}"
    if operation in "+-":
        sign = 1 if operation == "+" else -1
        correct = first + sign * second
        draft = Draft("Вычисли", prompt, number(correct))
        if b + sign * d != 0:
            draft.add(number(sp.Rational(a + sign * c, b + sign * d)), ErrorType.FRACTIONS)
        draft.add(number(sp.Rational(a + sign * c, b * d)), ErrorType.FRACTIONS)
        draft.add(number(sp.Rational(a * d + sign * c, b * d)), ErrorType.FRACTIONS)
        draft.add(number(first - sign * second), ErrorType.SIGN)
    elif operation == "*":
        correct = first * second
        draft = Draft("Вычисли", prompt, number(correct))
        draft.add(number(first / second), ErrorType.FRACTIONS)
        draft.add(number(sp.Rational(a * c, b + d)), ErrorType.FRACTIONS)
        draft.add(number(sp.Rational(a * c, b)), ErrorType.FRACTIONS)
    else:
        correct = first / second
        draft = Draft("Вычисли", prompt, number(correct))
        draft.add(number(first * second), ErrorType.FRACTIONS)
        draft.add(number(second / first), ErrorType.FRACTIONS)
        draft.add(number(sp.Rational(a, d * c)), ErrorType.FRACTIONS)
    draft.add(number(sp.Rational(correct.p + 1, correct.q)), ErrorType.ARITHMETIC)
    return draft


def powers(rng: random.Random, difficulty: int) -> Draft:
    if rng.random() < 0.5:
        m, n = rng.randint(2, 4 + difficulty), rng.randint(2, 4 + difficulty)
        k = rng.randint(2, m + n - (1 if difficulty == 1 else -2))
        prompt = rf"\frac{{a^{{{m}}} \cdot a^{{{n}}}}}{{a^{{{k}}}}}"
        correct = A**m * A**n / A**k
        draft = Draft("Упрости выражение", prompt, expression(correct))
        draft.add(expression(A ** (m * n - k)), ErrorType.POWERS)
        draft.add(expression(A ** (m + n + k)), ErrorType.SIGN)
        if (m + n) % k == 0:
            draft.add(expression(A ** ((m + n) // k)), ErrorType.POWERS)
        draft.add(expression(A ** (m * n) / A**k), ErrorType.POWERS)
        draft.add(expression(A ** (m + n - k + 1)), ErrorType.ARITHMETIC)
        return draft
    m, n = rng.randint(2, 3 + difficulty), rng.randint(2, 3 + difficulty)
    k = nonzero(rng, -difficulty, 3 + difficulty)
    tail = "a" if k == 1 else f"a^{{{k}}}"
    prompt = rf"\left(a^{{{m}}}\right)^{{{n}}} \cdot {tail}"
    correct = (A**m) ** n * A**k
    draft = Draft("Упрости выражение", prompt, expression(correct))
    draft.add(expression(A ** (m + n + k)), ErrorType.POWERS)
    draft.add(expression(A ** (m * n * k)), ErrorType.POWERS)
    draft.add(expression(A ** (m * n - k)), ErrorType.SIGN)
    draft.add(expression(A ** (m**n + k)), ErrorType.POWERS)
    return draft


def roots(rng: random.Random, difficulty: int) -> Draft:
    form = rng.choice(["sum", "product", "square"] if difficulty > 1 else ["sum", "product"])
    if form == "sum":
        base = rng.choice([2, 3, 5, 6, 7])
        p, q = rng.sample(range(2, 4 + difficulty), 2)
        sign = rng.choice([1, -1])
        first, second = p * p * base, q * q * base
        operator = "+" if sign == 1 else "-"
        prompt = rf"\sqrt{{{first}}} {operator} \sqrt{{{second}}}"
        correct = sp.sqrt(first) + sign * sp.sqrt(second)
        draft = Draft("Упрости выражение", prompt, number(correct))
        if first + sign * second > 0:
            draft.add(number(sp.sqrt(first + sign * second)), ErrorType.ROOTS)
        draft.add(number((p - sign * q) * sp.sqrt(base)), ErrorType.SIGN)
        draft.add(number((p * p + sign * q * q) * sp.sqrt(base)), ErrorType.ROOTS)
        draft.add(number((p + sign * q) * base), ErrorType.ROOTS)
        return draft
    if form == "product":
        root = rng.randint(2, 4 + 2 * difficulty)
        divisors = [d for d in range(2, root * root) if (root * root) % d == 0]
        require(bool(divisors))
        left = rng.choice(divisors)
        right = root * root // left
        require(left != right)
        prompt = rf"\sqrt{{{left}}} \cdot \sqrt{{{right}}}"
        draft = Draft("Вычисли", prompt, number(sp.sqrt(left) * sp.sqrt(right)))
        draft.add(number(sp.sqrt(left + right)), ErrorType.ROOTS)
        draft.add(number(left * right), ErrorType.ROOTS)
        draft.add(number(sp.Rational(left * right, 2)), ErrorType.ROOTS)
        draft.add(number(root + 1), ErrorType.ARITHMETIC)
        return draft
    p, q = rng.sample([2, 3, 5, 6, 7], 2)
    prompt = rf"\left(\sqrt{{{p}}} - \sqrt{{{q}}}\right)^{{2}}"
    correct = sp.expand((sp.sqrt(p) - sp.sqrt(q)) ** 2)
    draft = Draft("Упрости выражение", prompt, number(correct))
    draft.add(number(p - q), ErrorType.DISTRIBUTION)
    draft.add(number(p + q), ErrorType.DISTRIBUTION)
    draft.add(number(p + q + 2 * sp.sqrt(p * q)), ErrorType.SIGN)
    draft.add(number(p + q - sp.sqrt(p * q)), ErrorType.FORMULA)
    return draft
