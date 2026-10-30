import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import sympy as sp

from yasno.math.equivalence import equivalent
from yasno.math.errors import ErrorType
from yasno.math.parsing import Answer, Equation, parse_expression, parse_line
from yasno.math.solving import answer_latex, same_set

X = sp.Symbol("x", real=True)
Y = sp.Symbol("y", real=True)
CHOICES = 4


class ValueKind(StrEnum):
    NUMBER = "number"
    EXPRESSION = "expression"
    SET = "set"
    POINT = "point"


@dataclass(frozen=True, slots=True)
class Value:
    kind: ValueKind
    data: Any
    variable: Any = X

    def latex(self) -> str:
        match self.kind:
            case ValueKind.SET:
                return answer_latex(self.data, self.variable)
            case ValueKind.POINT:
                return "(" + "; ".join(str(sp.latex(item)) for item in self.data) + ")"
            case _:
                return str(sp.latex(self.data))

    def same_as(self, other: "Value") -> bool:
        if self.kind is not other.kind:
            return False
        match self.kind:
            case ValueKind.SET:
                return bool(same_set(self.data, other.data))
            case ValueKind.POINT:
                return len(self.data) == len(other.data) and all(
                    sp.simplify(a - b) == 0 for a, b in zip(self.data, other.data, strict=True)
                )
            case _:
                return bool(equivalent(self.data, other.data))

    def round_trips(self) -> bool:
        match self.kind:
            case ValueKind.SET:
                return isinstance(parse_line(self.latex()), Answer | Equation)
            case ValueKind.POINT:
                return True
            case _:
                return parse_expression(self.latex()) is not None

    def is_valid(self) -> bool:
        items = self.data if self.kind is ValueKind.POINT else [self.data]
        for item in items:
            if isinstance(item, sp.Set):
                continue
            if item.has(sp.zoo, sp.nan, sp.oo, -sp.oo) or item.has(sp.I):
                return False
        return True


def number(value: Any) -> Value:
    return Value(ValueKind.NUMBER, sp.nsimplify(value))


def expression(value: Any) -> Value:
    return Value(ValueKind.EXPRESSION, value)


def roots(*values: Any) -> Value:
    return Value(ValueKind.SET, sp.FiniteSet(*values))


def solution_set(values: Any) -> Value:
    return Value(ValueKind.SET, values)


def point(*values: Any) -> Value:
    return Value(ValueKind.POINT, tuple(sp.nsimplify(value) for value in values))


@dataclass(slots=True)
class Draft:
    instruction: str
    prompt: str
    correct: Value
    distractors: list[tuple[Value, ErrorType]] = field(default_factory=list)

    def add(self, value: Value, error: ErrorType) -> None:
        self.distractors.append((value, error))


class Rejected(Exception):
    pass


type Recipe = Callable[[random.Random, int], Draft]


def require(condition: bool) -> None:
    if not condition:
        raise Rejected


def nonzero(rng: random.Random, low: int, high: int) -> int:
    while True:
        value = rng.randint(low, high)
        if value != 0:
            return value


def span(difficulty: int) -> int:
    return 3 + 3 * difficulty


def signed(value: Any) -> str:
    text = str(sp.latex(value))
    return f"- {text[1:]}" if text.startswith("-") else f"+ {text}"


def linear_latex(coefficient: int, constant: int, symbol: str = "x") -> str:
    head = {1: symbol, -1: f"-{symbol}"}.get(coefficient, f"{coefficient}{symbol}")
    if coefficient == 0:
        return str(constant)
    if constant == 0:
        return head
    return f"{head} {signed(constant)}"


def poly_latex(expr: Any) -> str:
    return str(sp.latex(sp.expand(expr)))
