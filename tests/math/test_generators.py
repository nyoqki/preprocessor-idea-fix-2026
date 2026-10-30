import random
import re
from collections.abc import Callable
from typing import Any

import pytest
import sympy as sp

from yasno.math.equivalence import equivalent
from yasno.math.errors import ErrorType
from yasno.math.generators import GeneratedProblem, generate, supported_topics
from yasno.math.parsing import (
    Answer,
    Equation,
    Expression,
    Inequality,
    System,
    parse_expression,
    parse_line,
)
from yasno.math.solving import same_set, solve_equation, solve_inequality, solve_system
from yasno.math.topics import TOPICS_BY_CODE

SEEDS = range(24)
x = sp.Symbol("x", real=True)

type Checker = Callable[[GeneratedProblem], Callable[[str], bool]]


def _single_variable(parts: tuple[Any, ...]) -> Any:
    symbols = set().union(*(part.free_symbols for part in parts))
    assert len(symbols) == 1
    return next(iter(symbols))


def _set_answer(expected: Any) -> Callable[[str], bool]:
    def check(latex: str) -> bool:
        answer = parse_line(latex)
        if isinstance(answer, Equation) and answer.lhs.is_Symbol:
            return bool(same_set(sp.FiniteSet(answer.rhs), expected))
        assert isinstance(answer, Answer), latex
        return bool(same_set(answer.values, expected))

    return check


def _equation(problem: GeneratedProblem) -> Callable[[str], bool]:
    statement = parse_line(problem.prompt_latex)
    if isinstance(statement, Expression):
        return _expression_value(statement.expr)
    assert isinstance(statement, Equation), problem.prompt_latex
    variable = _single_variable((statement.lhs, statement.rhs))
    return _set_answer(solve_equation(statement.lhs, statement.rhs, variable))


def _inequality(problem: GeneratedProblem) -> Callable[[str], bool]:
    statement = parse_line(problem.prompt_latex)
    assert isinstance(statement, Inequality), problem.prompt_latex
    variable = _single_variable(statement.parts)
    return _set_answer(solve_inequality(statement.parts, statement.ops, variable))


def _system(problem: GeneratedProblem) -> Callable[[str], bool]:
    statement = parse_line(problem.prompt_latex)
    assert isinstance(statement, System), problem.prompt_latex
    members = [(m.lhs, m.rhs) for m in statement.members if isinstance(m, Equation)]
    variables = sorted(
        set().union(*(lhs.free_symbols | rhs.free_symbols for lhs, rhs in members)), key=str
    )
    expected = solve_system(members, variables)

    def check(latex: str) -> bool:
        answer = parse_line(latex)
        assert isinstance(answer, Answer), latex
        return [tuple(point) for point in answer.points] == [tuple(p) for p in expected]

    return check


def _expression_value(expected: Any) -> Callable[[str], bool]:
    def check(latex: str) -> bool:
        value = parse_expression(latex)
        assert value is not None, latex
        return bool(equivalent(value, expected))

    return check


def _expression(problem: GeneratedProblem) -> Callable[[str], bool]:
    value = parse_expression(problem.prompt_latex)
    assert value is not None, problem.prompt_latex
    return _expression_value(value)


def _derivative(problem: GeneratedProblem) -> Callable[[str], bool]:
    function = parse_expression(problem.prompt_latex.split("=", 1)[1])
    assert function is not None
    return _expression_value(sp.diff(function, x))


def _progression(problem: GeneratedProblem) -> Callable[[str], bool]:
    numbers = [int(value) for value in re.findall(r"-?\d+", problem.prompt_latex)]
    _, first, step, n = numbers
    if problem.prompt_latex.startswith("a"):
        expected = first + (n - 1) * step
    else:
        expected = first * step ** (n - 1)
    return _expression_value(sp.Integer(expected))


CHECKERS: dict[str, Checker] = {
    "arith.fractions": _expression,
    "arith.powers": _expression,
    "alg.roots": _expression,
    "alg.expressions": _expression,
    "alg.factoring": _expression,
    "alg.progressions": _progression,
    "alg.linear_eq": _equation,
    "alg.quadratic_eq": _equation,
    "alg.rational_eq": _equation,
    "alg.exponential": _equation,
    "alg.logarithms": _equation,
    "alg.systems": _system,
    "alg.linear_ineq": _inequality,
    "alg.quadratic_ineq": _inequality,
    "calc.derivative": _derivative,
}


def test_supported_topics() -> None:
    assert supported_topics() == frozenset(CHECKERS)
    assert supported_topics() <= frozenset(TOPICS_BY_CODE)


@pytest.mark.parametrize("topic", sorted(CHECKERS))
def test_generated_problems_are_well_formed(topic: str) -> None:
    for seed in SEEDS:
        difficulty = seed % 3 + 1
        problem = generate(topic, random.Random(seed), difficulty=difficulty)
        assert problem.topic_code == topic
        assert problem.difficulty == difficulty
        assert re.search(r"[А-Яа-я]", problem.instruction)
        assert len(problem.choices) == 4
        assert len({choice.latex for choice in problem.choices}) == 4
        assert sum(choice.correct for choice in problem.choices) == 1
        for choice in problem.choices:
            assert (choice.error_type is None) == choice.correct
        is_correct = CHECKERS[topic](problem)
        verdicts = [is_correct(choice.latex) for choice in problem.choices]
        assert verdicts == [choice.correct for choice in problem.choices], (seed, problem)


@pytest.mark.parametrize("topic", sorted(CHECKERS))
def test_generation_is_deterministic(topic: str) -> None:
    first = generate(topic, random.Random(7), difficulty=2)
    second = generate(topic, random.Random(7), difficulty=2)
    assert first == second


@pytest.mark.parametrize(
    ("topic", "focus"),
    [
        ("alg.linear_eq", ErrorType.SIGN),
        ("alg.quadratic_ineq", ErrorType.SIGN),
        ("alg.linear_ineq", ErrorType.INEQUALITY_FLIP),
        ("alg.rational_eq", ErrorType.DOMAIN),
        ("arith.fractions", ErrorType.FRACTIONS),
        ("calc.derivative", ErrorType.FORMULA),
    ],
)
def test_focus_biases_distractors(topic: str, focus: ErrorType) -> None:
    for seed in range(10):
        problem = generate(topic, random.Random(seed), focus=focus)
        assert any(choice.error_type is focus for choice in problem.choices)


def test_unknown_topic_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported topic"):
        generate("geom.planimetry", random.Random(1))


def test_difficulty_is_clamped() -> None:
    assert generate("alg.linear_eq", random.Random(1), difficulty=9).difficulty == 3
    assert generate("alg.linear_eq", random.Random(1), difficulty=0).difficulty == 1
