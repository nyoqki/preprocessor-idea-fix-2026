import re
from collections.abc import Sequence
from typing import Any

from yasno.math.checkers import (
    Checker,
    DerivativeChecker,
    ExpressionChecker,
    Item,
    SetChecker,
    SystemChecker,
)
from yasno.math.limits import MathTimeout, time_limit
from yasno.math.parsing import (
    Answer,
    Chain,
    Disjunction,
    Equation,
    Expression,
    Inequality,
    Note,
    Op,
    Statement,
    System,
    Unparseable,
    parse_steps,
)
from yasno.math.solving import Unsupported
from yasno.math.verification import ProblemKind, Status, StepStatus, Verification

MAX_LINES = 40
TIME_BUDGET = 2.8

_HINTS = (
    (re.compile(r"производн", re.IGNORECASE), ProblemKind.DERIVATIVE),
    (re.compile(r"неравенств", re.IGNORECASE), ProblemKind.INEQUALITY),
    (re.compile(r"систем", re.IGNORECASE), ProblemKind.SYSTEM),
    (
        re.compile(
            r"упрост|преобраз|вычисл|значени[ея]\s+выражени|раскрой|разлож|сократ|представ",
            re.IGNORECASE,
        ),
        ProblemKind.EXPRESSION,
    ),
    (re.compile(r"уравнени|корн|реши", re.IGNORECASE), ProblemKind.EQUATION),
)


def _hint(task: str | None) -> ProblemKind | None:
    if not task:
        return None
    for pattern, kind in _HINTS:
        if pattern.search(task):
            return kind
    return None


def _free(statement: Statement) -> set[Any]:
    found: set[Any] = set()
    match statement:
        case Expression(expr=expr):
            found |= expr.free_symbols
        case Equation(lhs=lhs, rhs=rhs):
            found |= lhs.free_symbols | rhs.free_symbols
        case Inequality(parts=parts) | Chain(parts=parts):
            for part in parts:
                found |= part.free_symbols
        case System(members=members) | Disjunction(members=members):
            for member in members:
                found |= _free(member)
    return found


def _is_task(statement: Statement) -> bool:
    return isinstance(statement, Expression | Equation | Inequality | Chain | System | Disjunction)


def _is_answer(statement: Statement) -> bool:
    return isinstance(statement, Answer)


def _kind_of(statement: Statement, hint: ProblemKind | None) -> ProblemKind:
    symbols = _free(statement)
    if hint is ProblemKind.DERIVATIVE:
        return ProblemKind.DERIVATIVE
    match statement:
        case Expression():
            return ProblemKind.EXPRESSION
        case Chain(ops=ops) if all(op is Op.EQ for op in ops):
            return ProblemKind.EXPRESSION
        case Equation():
            if not symbols or hint is ProblemKind.EXPRESSION:
                return ProblemKind.EXPRESSION
            if len(symbols) == 1:
                return ProblemKind.EQUATION
        case Inequality() if len(symbols) == 1:
            return ProblemKind.INEQUALITY
        case Disjunction() if len(symbols) == 1:
            return ProblemKind.EQUATION
        case System(members=members):
            if len(symbols) >= 2 and all(isinstance(m, Equation) for m in members):
                return ProblemKind.SYSTEM
            if len(symbols) == 1:
                if all(isinstance(m, Equation) for m in members):
                    return ProblemKind.EQUATION
                return ProblemKind.INEQUALITY
    return ProblemKind.UNKNOWN


def _function_of(statement: Statement) -> Any:
    match statement:
        case Expression(expr=expr):
            return expr
        case Equation(lhs=lhs, rhs=rhs) if lhs.is_Symbol:
            return rhs
        case Chain(parts=parts):
            return parts[-1]
    return None


def _build(task: Item, kind: ProblemKind, chained: bool) -> Checker:
    statement = task.statement
    symbols = sorted(_free(statement), key=str)
    match kind:
        case ProblemKind.EXPRESSION:
            return ExpressionChecker(task, chained=chained)
        case ProblemKind.EQUATION | ProblemKind.INEQUALITY:
            return SetChecker(statement, symbols[0], inequality=kind is ProblemKind.INEQUALITY)
        case ProblemKind.SYSTEM if isinstance(statement, System):
            return SystemChecker(statement)
        case ProblemKind.DERIVATIVE:
            function = _function_of(statement)
            if function is None:
                raise Unsupported
            variables = sorted(function.free_symbols, key=str)
            if len(variables) != 1:
                raise Unsupported
            return DerivativeChecker(function, variables[0])
    raise Unsupported


def _items(lines: Sequence[str]) -> list[Item]:
    items = []
    for index, line in enumerate(lines[:MAX_LINES]):
        if not line or not line.strip():
            continue
        for statement in parse_steps(line):
            items.append(Item(index, statement))
    return items


def _task_item(task: str | None, items: list[Item]) -> tuple[Item | None, list[Item], bool]:
    if task:
        for statement in reversed(parse_steps(task)):
            if _is_task(statement):
                return Item(-1, statement), items, False
    for position, item in enumerate(items):
        if _is_task(item.statement):
            return item, items[position + 1 :], True
        if isinstance(item.statement, Unparseable):
            return None, items, False
    return None, items, False


def _first_unparseable(items: list[Item]) -> int | None:
    for item in items:
        if isinstance(item.statement, Unparseable):
            return item.index
    return None


def _status(checker: Checker, items: list[Item], *, timed_out: bool) -> Status:
    if checker.error is not None:
        return Status.ERROR
    if timed_out:
        return Status.UNSUPPORTED
    failed = sum(isinstance(item.statement, Unparseable) for item in items)
    meaningful = sum(not isinstance(item.statement, Note | Unparseable) for item in items)
    if checker.complete and failed <= max(1, meaningful // 2):
        return Status.CORRECT
    if _first_unparseable(items) is not None:
        return Status.UNPARSEABLE
    checked = [step for step in checker.steps if step.status is not StepStatus.SKIPPED]
    if checked and all(step.status is StepStatus.UNSUPPORTED for step in checked):
        return Status.UNSUPPORTED
    return Status.INCOMPLETE


def _result(
    checker: Checker, kind: ProblemKind, items: list[Item], *, timed_out: bool
) -> Verification:
    error = checker.error
    return Verification(
        status=_status(checker, items, timed_out=timed_out),
        problem_kind=kind,
        first_error_step=error.index if error is not None else None,
        error_type=error.error_type if error is not None else None,
        expected=error.expected if error is not None else None,
        got=error.got if error is not None else None,
        steps=tuple(checker.steps),
        final_answer=checker.final_answer,
        unparseable_step=_first_unparseable(items),
        solution=checker.solution,
        variable=checker.variable_name,
    )


def _run(lines: Sequence[str], task: str | None) -> Verification:
    items = _items(lines)
    hint = _hint(task)
    task_item, rest, chained = _task_item(task, items)
    if task_item is None:
        failed = _first_unparseable(items)
        if failed is None and items and not any(_is_answer(item.statement) for item in items):
            failed = items[0].index
        if failed is not None:
            return Verification(
                status=Status.UNPARSEABLE,
                problem_kind=hint or ProblemKind.UNKNOWN,
                unparseable_step=failed,
            )
        return Verification(status=Status.UNSUPPORTED, problem_kind=hint or ProblemKind.UNKNOWN)
    kind = _kind_of(task_item.statement, hint)
    try:
        checker = _build(task_item, kind, chained)
    except Unsupported:
        return Verification(status=Status.UNSUPPORTED, problem_kind=kind)
    timed_out = False
    try:
        for item in rest:
            checker.process(item)
            if checker.error is not None:
                break
        if checker.error is None:
            checker.finish()
    except MathTimeout:
        timed_out = True
    except Unsupported:
        timed_out = True
    return _result(checker, kind, items, timed_out=timed_out)


def verify_solution(lines: Sequence[str], task: str | None = None) -> Verification:
    try:
        with time_limit(TIME_BUDGET):
            return _run(lines, task)
    except MathTimeout:
        return Verification(status=Status.UNSUPPORTED, problem_kind=ProblemKind.UNKNOWN)
    except (RecursionError, MemoryError, Exception):
        return Verification(status=Status.UNSUPPORTED, problem_kind=ProblemKind.UNKNOWN)
