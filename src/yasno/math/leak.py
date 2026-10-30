import re
from collections.abc import Iterable, Sequence
from typing import Any

import sympy as sp

from yasno.math.equivalence import equivalent
from yasno.math.limits import MathTimeout, reraise_if_expired, time_limit
from yasno.math.parsing import (
    Answer,
    Chain,
    Equation,
    Expression,
    Inequality,
    Statement,
    parse_expression,
    parse_line,
)
from yasno.math.solving import Unsupported, finite_elements, is_finite, same_set, solve_inequality
from yasno.math.verification import ProblemKind, Verification

_NUMBER = re.compile(r"(?<![\w^_.,])[-−]?\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?(?![\w.,]?\d)")
_VULGAR = {"½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4"}
_ASSIGNMENT = re.compile(
    r"(?<![А-Яа-яЁёA-Za-z])[a-zA-Z](?:_?\{?\d\}?|[₁₂])?\s*(?:=|равен|равн[а-яё]*|будет|получ[а-яё]*)\s*"
    r"(?P<value>[-−]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)",
    re.IGNORECASE,
)
_NAMED_VALUE = re.compile(
    r"(?:дискриминант|корн[а-яё]*|корень|ответ|значени[а-яё]*|результат)[а-яё]*\s*"
    r"(?:равен|равн[а-яё]*|будет|получ[а-яё]*|=|:|—|-)\s*"
    r"(?P<value>[-−]?\s*\d+(?:[.,]\d+)?(?:\s*/\s*\d+)?)",
    re.IGNORECASE,
)
_CYRILLIC = re.compile(r"[А-Яа-яЁё]+")
_TRIVIAL = (sp.Integer(0), sp.Integer(1))


def _number(text: str) -> Any:
    cleaned = text.replace("−", "-").replace(",", ".").replace(" ", "")
    for symbol, fraction in _VULGAR.items():
        cleaned = cleaned.replace(symbol, fraction)
    try:
        if "/" in cleaned:
            numerator, denominator = cleaned.split("/", 1)
            return sp.Rational(sp.Rational(numerator), sp.Rational(denominator))
        return sp.Rational(cleaned)
    except (ValueError, TypeError, ZeroDivisionError):
        return None


def _numbers(text: str) -> list[Any]:
    for symbol, fraction in _VULGAR.items():
        text = text.replace(symbol, f" {fraction} ")
    found = [_number(match.group()) for match in _NUMBER.finditer(text)]
    return [value for value in found if value is not None]


def _same_number(first: Any, second: Any) -> bool:
    try:
        return abs(complex(sp.N(first - second, 20))) < 1e-9
    except (TypeError, ValueError):
        return False


def _contains_number(values: Iterable[Any], value: Any) -> bool:
    return any(_same_number(value, item) for item in values)


def _pieces(latex: str | None) -> list[str]:
    if not latex:
        return []
    return [piece for piece in re.split(r";|\\cup|,\\ ", latex) if piece.strip()]


def _secret_values(verification: Verification) -> list[Any]:
    values: list[Any] = []
    for source in (verification.solution, verification.expected):
        statement = parse_line(source) if source else None
        if isinstance(statement, Answer) and is_finite(statement.values):
            values.extend(finite_elements(statement.values))
            continue
        if isinstance(statement, Answer):
            boundary = statement.values.boundary
            if is_finite(boundary):
                values.extend(finite_elements(boundary))
            continue
        for piece in _pieces(source):
            if "=" in piece:
                value = parse_expression(piece.split("=")[-1])
                if value is not None and value.is_number:
                    values.append(value)
            else:
                value = parse_expression(piece)
                if value is not None and value.is_number and value.is_finite:
                    values.append(value)
    return [value for value in values if value.is_finite]


def _secret_expressions(verification: Verification) -> list[Any]:
    found = []
    for source in (verification.expected, verification.solution):
        if not source or verification.problem_kind not in (
            ProblemKind.EXPRESSION,
            ProblemKind.DERIVATIVE,
        ):
            continue
        value = parse_expression(source)
        if value is not None and value.free_symbols:
            found.append(value)
    return found


def _secret_set(verification: Verification) -> Any:
    if verification.problem_kind is not ProblemKind.INEQUALITY or not verification.solution:
        return None
    statement = parse_line(verification.solution)
    return statement.values if isinstance(statement, Answer) else None


def _fragments(text: str) -> list[str]:
    chunks = []
    for part in _CYRILLIC.split(text):
        for chunk in re.split(r"[!?«»\"]|\.\s|:\s", part):
            cleaned = chunk.strip(" .,;:—")
            if re.search(r"[0-9a-zA-Z]", cleaned) and len(cleaned) <= 200:
                chunks.append(cleaned)
    return chunks


def _statement_values(statement: Statement) -> list[Any]:
    match statement:
        case Answer(values=values) if is_finite(values):
            return finite_elements(values)
        case Equation(lhs=lhs, rhs=rhs) if lhs.is_Symbol and rhs.is_number:
            return [rhs]
        case Equation(lhs=lhs, rhs=rhs) if rhs.is_Symbol and lhs.is_number:
            return [lhs]
        case Chain(parts=parts) if parts[0].is_Symbol and parts[-1].is_number:
            return [parts[-1]]
    return []


def _statement_set(statement: Statement) -> Any:
    match statement:
        case Answer(values=values):
            return values
        case Inequality(parts=parts, ops=ops):
            symbols = set().union(*(part.free_symbols for part in parts))
            if len(symbols) == 1:
                try:
                    return solve_inequality(parts, ops, next(iter(symbols)))
                except Unsupported:
                    return None
    return None


def _statement_expressions(statement: Statement) -> list[Any]:
    match statement:
        case Expression(expr=expr):
            return [expr]
        case Equation(lhs=lhs, rhs=rhs):
            return [lhs, rhs]
        case Chain(parts=parts):
            return list(parts)
    return []


def _context_numbers(context: Sequence[str]) -> list[Any]:
    found: list[Any] = []
    for line in context:
        found.extend(_numbers(line))
    return found


def _check(text: str, verification: Verification, context: Sequence[str]) -> bool:
    values = _secret_values(verification)
    for match in [*_ASSIGNMENT.finditer(text), *_NAMED_VALUE.finditer(text)]:
        value = _number(match.group("value"))
        if value is not None and _contains_number(values, value):
            return True
    allowed = [*_context_numbers(context), *_TRIVIAL]
    for value in _numbers(text):
        if _contains_number(values, value) and not _contains_number(allowed, value):
            return True
    expressions = _secret_expressions(verification)
    target = _secret_set(verification)
    for fragment in _fragments(text):
        statement = parse_line(fragment)
        if any(_contains_number(values, value) for value in _statement_values(statement)):
            return True
        if target is not None:
            candidate = _statement_set(statement)
            if candidate is not None and same_set(candidate, target):
                return True
        for expr in _statement_expressions(statement):
            if expr.free_symbols and any(equivalent(expr, secret) for secret in expressions):
                return True
    return False


def reveals_answer(text: str, verification: Verification, *, context: Sequence[str] = ()) -> bool:
    if not text.strip():
        return False
    try:
        with time_limit(1.5):
            return _check(text, verification, context)
    except MathTimeout:
        reraise_if_expired()
        return True
    except Exception:
        return True
