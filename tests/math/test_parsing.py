import time
from typing import Any

import pytest
import sympy as sp

from yasno.math.parsing import (
    Answer,
    Chain,
    Disjunction,
    Equation,
    Expression,
    Inequality,
    Note,
    NoteKind,
    Op,
    System,
    Unparseable,
    parse_expression,
    parse_line,
    parse_steps,
)

x = sp.Symbol("x", real=True)
y = sp.Symbol("y", real=True)


def _same(left: Any, right: Any) -> bool:
    return bool(sp.simplify(left - right) == 0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2x+3(x-1)", 5 * x - 3),
        (r"\frac{x+1}{2}", (x + 1) / 2),
        ("x^2 - 5x + 6", x**2 - 5 * x + 6),
        ("x**2", x**2),
        ("x²+x³", x**2 + x**3),
        (r"2 \cdot 3x", 6 * x),
        (r"2 \times 3", sp.Integer(6)),
        ("2 × 3 · x", 6 * x),
        ("6 : 4", sp.Rational(3, 2)),
        ("0,5x", x / 2),
        ("−x − 1", -x - 1),
        (r"\left(x+1\right)^2", (x + 1) ** 2),
        (r"\sqrt{x+1}", sp.sqrt(x + 1)),
        ("√(x+1)", sp.sqrt(x + 1)),
        ("√16", sp.Integer(4)),
        ("sqrt(9)", sp.Integer(3)),
        (r"\log_2 8", sp.Integer(3)),
        (r"\lg 100", sp.Integer(2)),
        ("lg(1000)", sp.Integer(3)),
        (r"\ln x", sp.log(x)),
        (r"\sin x + \cos x", sp.sin(x) + sp.cos(x)),
        ("tg x", sp.tan(x)),
        (r"\dfrac{1}{2} + \tfrac12", sp.Integer(1)),
        ("2^(x+1)", 2 ** (x + 1)),
        ("x^10", x**10),
        ("½x", x / 2),
    ],
)
def test_parse_expression(text: str, expected: Any) -> None:
    value = parse_expression(text)
    assert value is not None
    assert _same(value, expected)


def test_equation_keeps_raw_form() -> None:
    statement = parse_line("-(x-3) = 2(x+1)")
    assert isinstance(statement, Equation)
    assert statement.raw_lhs.is_Mul
    assert _same(statement.lhs, 3 - x)
    assert _same(statement.rhs, 2 * x + 2)


@pytest.mark.parametrize(
    ("text", "ops"),
    [
        (r"\frac{x+1}{2} \le 3", (Op.LE,)),
        ("x ≥ 2", (Op.GE,)),
        ("1 < 2x - 3 < 5", (Op.LT, Op.LT)),
        (r"-1 \leqslant x < 4", (Op.LE, Op.LT)),
    ],
)
def test_inequalities(text: str, ops: tuple[Op, ...]) -> None:
    statement = parse_line(text)
    assert isinstance(statement, Inequality)
    assert statement.ops == ops


@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("x_1=2, x_2=3", sp.FiniteSet(2, 3)),
        ("x₁ = 2; x₂ = 3", sp.FiniteSet(2, 3)),
        ("x=2 или x=3", sp.FiniteSet(2, 3)),
        (r"x_{1,2} = \frac{5 \pm 1}{2}", sp.FiniteSet(2, 3)),
        ("Ответ: 5", sp.FiniteSet(5)),
        ("Ответ: x=5", sp.FiniteSet(5)),
        ("Ответ: -2; 3", sp.FiniteSet(-2, 3)),
        ("корней нет", sp.EmptySet),
        ("Ответ: нет решений", sp.EmptySet),
        ("∅", sp.EmptySet),
        (r"x \in \varnothing", sp.EmptySet),
        (r"x\in(-\infty;3]", sp.Interval(-sp.oo, 3)),
        ("x ∈ (−∞; 3] ∪ [5; +∞)", sp.Union(sp.Interval(-sp.oo, 3), sp.Interval(5, sp.oo))),
        (r"\text{Ответ: } x \in [2;3)", sp.Interval.Ropen(2, 3)),
        ("Ответ: x ≤ 3", sp.Interval(-sp.oo, 3)),
        ("x — любое число", sp.Reals),
        ("Ответ: x=1,5", sp.FiniteSet(sp.Rational(3, 2))),
    ],
)
def test_answers(text: str, values: Any) -> None:
    statement = parse_line(text)
    assert isinstance(statement, Answer)
    assert statement.values == values


def test_point_answers() -> None:
    statement = parse_line("Ответ: (2; 3)")
    assert isinstance(statement, Answer)
    assert statement.points == ((2, 3),)
    pair = parse_line("x=2, y=3")
    assert isinstance(pair, Answer)
    assert pair.variables == (x, y)
    assert pair.points == ((2, 3),)


@pytest.mark.parametrize(
    "text",
    [
        r"\begin{cases} x+y=5 \\ x-y=1 \end{cases}",
        r"\left\{\begin{array}{l}x+y=5\\x-y=1\end{array}\right.",
        "{x+y=5; x-y=1}",
    ],
)
def test_systems(text: str) -> None:
    statement = parse_line(text)
    assert isinstance(statement, System)
    assert len(statement.members) == 2


def test_chains_and_continuations() -> None:
    chain = parse_line(r"D = (-5)^2 - 4 \cdot 1 \cdot 6 = 25 - 24 = 1")
    assert isinstance(chain, Chain)
    assert len(chain.parts) == 4
    continuation = parse_line("= x^2 + 2x")
    assert isinstance(continuation, Expression)
    assert continuation.continuation


def test_disjunction_and_vieta() -> None:
    assert isinstance(parse_line("x = 0 или x - 4 = 0"), Disjunction)
    assert isinstance(parse_line(r"x_1 + x_2 = 5, x_1 \cdot x_2 = 6"), System)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("ОДЗ: x ≠ 2", NoteKind.DOMAIN),
        (r"x \neq 0", NoteKind.DOMAIN),
        ("x = 2 — посторонний корень", NoteKind.REJECT),
        ("x=-1 не удовлетворяет ОДЗ", NoteKind.REJECT),
        ("Найдём дискриминант", NoteKind.TEXT),
        ("+ − +", NoteKind.TEXT),
    ],
)
def test_notes(text: str, kind: NoteKind) -> None:
    statement = parse_line(text)
    assert isinstance(statement, Note)
    assert statement.kind is kind


def test_steps_split_on_implication() -> None:
    steps = parse_steps(r"3x - 4 > 2 \Rightarrow 3x > 6 ⇒ x > 2")
    assert [type(step) for step in steps] == [Inequality, Inequality, Inequality]


def test_ocr_noise_is_tolerated() -> None:
    assert isinstance(parse_line("1) 2x - 3 = 5 | +3"), Equation)
    assert isinstance(parse_line("$x^{2}-4x=0$."), Equation)
    assert isinstance(parse_line("  x = 3 ,"), Equation)


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('ls')",
        "x.__class__.__bases__",
        "lambda: 1",
        "eval(1)",
        "open('/etc/passwd')",
        "9^{9^{9}}",
        "9**9**9**9",
        "10^{100000}",
        "123456789012345678901234567890",
        "x" * 1000,
        "(" * 300 + "x" + ")" * 300,
        "2x+",
        "",
    ],
)
def test_malicious_and_broken_input_is_rejected(text: str) -> None:
    started = time.monotonic()
    statement = parse_line(text)
    assert isinstance(statement, Unparseable | Note)
    assert time.monotonic() - started < 2.5
