from dataclasses import dataclass
from typing import Any

import sympy as sp

from yasno.math.equivalence import (
    equivalent,
    proportional,
    simplified,
    to_latex,
)
from yasno.math.errors import ErrorType
from yasno.math.limits import limited
from yasno.math.mistakes import equation_mutations, expression_mutations, transfer_mutations
from yasno.math.parsing import (
    FLIPPED,
    INEQUALITY_OPS,
    Answer,
    Chain,
    Disjunction,
    Equation,
    Expression,
    Inequality,
    Note,
    NoteKind,
    Op,
    Statement,
    System,
    Unparseable,
    base_name,
)
from yasno.math.solving import (
    Unsupported,
    answer_latex,
    contains,
    critical_points,
    difference,
    finite_elements,
    is_finite,
    joint_domain,
    restrict,
    same_interior,
    same_set,
    solve_equation,
    solve_inequality,
    solve_system,
    subset,
)
from yasno.math.verification import ProblemKind, StepCheck, StepStatus

MAX_CLASSIFY_CANDIDATES = 40


@dataclass(frozen=True, slots=True)
class Item:
    index: int
    statement: Statement


class Checker:
    kind = ProblemKind.UNKNOWN

    def __init__(self) -> None:
        self.steps: list[StepCheck] = []
        self.error: StepCheck | None = None
        self.final_answer: str | None = None
        self.solution: str | None = None
        self.complete = False
        self.worked = False

    def record(self, index: int, status: StepStatus, kind: str) -> None:
        if index >= 0:
            self.steps.append(StepCheck(index, status, kind))
            if status in (StepStatus.OK, StepStatus.CONSEQUENCE):
                self.worked = True

    def fail(
        self,
        index: int,
        kind: str,
        error_type: ErrorType,
        expected: str | None = None,
        got: str | None = None,
    ) -> None:
        if self.error is not None:
            return
        check = StepCheck(index, StepStatus.ERROR, kind, error_type, expected, got)
        self.steps.append(check)
        self.error = check

    def process(self, item: Item) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        raise NotImplementedError

    @property
    def variable_name(self) -> str | None:
        return None


def _numeric_value(expr: Any) -> complex | None:
    try:
        return complex(sp.N(expr, 20))
    except (TypeError, ValueError, AttributeError):
        return None


def _numbers_equal(first: Any, second: Any) -> bool:
    a = _numeric_value(first)
    b = _numeric_value(second)
    if a is None or b is None:
        return False
    return abs(a - b) <= 1e-9 * (1 + abs(a))


def _relation_holds(left: Any, op: Op, right: Any) -> bool | None:
    if op is Op.EQ:
        return _numbers_equal(left, right)
    a = _numeric_value(left)
    b = _numeric_value(right)
    if a is None or b is None or abs(a.imag) > 1e-9 or abs(b.imag) > 1e-9:
        return None
    match op:
        case Op.LT:
            return a.real < b.real - 1e-12
        case Op.LE:
            return a.real <= b.real + 1e-12
        case Op.GT:
            return a.real > b.real + 1e-12
        case Op.GE:
            return a.real >= b.real - 1e-12
        case _:
            return not _numbers_equal(left, right)


def _residual_error(before: Any, after: Any) -> ErrorType:
    if equivalent(after, -before):
        return ErrorType.SIGN
    delta = limited(lambda: sp.simplify(after - before), 0.4, None)
    if delta is not None and delta.is_number:
        return ErrorType.ARITHMETIC
    both = limited(lambda: (sp.Poly(sp.expand(before)), sp.Poly(sp.expand(after))), 0.4, None)
    if both is not None and set(both[0].monoms()) == set(both[1].monoms()):
        return ErrorType.ARITHMETIC
    return ErrorType.OTHER


def classify_expression(before_raw: Any, before: Any, after: Any) -> ErrorType:
    for mutated, error in expression_mutations(before_raw)[:MAX_CLASSIFY_CANDIDATES]:
        if equivalent(mutated, after):
            return error
    return _residual_error(before, after)


class ExpressionChecker(Checker):
    kind = ProblemKind.EXPRESSION

    def __init__(self, start: Item, *, chained: bool) -> None:
        super().__init__()
        self.current: Any = None
        self.current_raw: Any = None
        self.first: Any = None
        parts, raws = _expression_parts(start.statement)
        if not parts:
            raise Unsupported
        self.current, self.current_raw, self.first = parts[0], raws[0], parts[0]
        self.solution = to_latex(simplified(self.first))
        if chained:
            for part, raw in zip(parts[1:], raws[1:], strict=True):
                self._compare(start.index, part, raw)

    def _compare(self, index: int, expr: Any, raw: Any) -> None:
        if self.error is not None:
            return
        same = equivalent(self.current, expr)
        if same is None:
            self.record(index, StepStatus.UNSUPPORTED, "expression")
        elif same:
            self.record(index, StepStatus.OK, "expression")
        else:
            error = classify_expression(self.current_raw, self.current, expr)
            self.fail(
                index, "expression", error, to_latex(simplified(self.current)), to_latex(expr)
            )
            return
        self.current, self.current_raw = expr, raw

    def process(self, item: Item) -> None:
        statement = item.statement
        if isinstance(statement, Unparseable):
            self.record(item.index, StepStatus.UNPARSEABLE, "line")
            return
        if isinstance(statement, Answer) and is_finite(statement.values):
            values = finite_elements(statement.values)
            if len(values) == 1:
                self._compare(item.index, values[0], values[0])
                return
        parts, raws = _expression_parts(statement)
        if not parts:
            self.record(item.index, StepStatus.SKIPPED, "note")
            return
        for part, raw in zip(parts, raws, strict=True):
            self._compare(item.index, part, raw)

    def finish(self) -> None:
        self.complete = self.worked
        self.final_answer = to_latex(self.current)


def _expression_parts(statement: Statement) -> tuple[list[Any], list[Any]]:
    match statement:
        case Expression(expr=expr, raw=raw):
            return [expr], [raw]
        case Chain(parts=parts, ops=ops, raw=raw) if all(op is Op.EQ for op in ops):
            return list(parts), list(raw)
        case Equation(lhs=lhs, rhs=rhs, raw_lhs=raw_lhs, raw_rhs=raw_rhs):
            return [lhs, rhs], [raw_lhs, raw_rhs]
    return [], []


class DerivativeChecker(Checker):
    kind = ProblemKind.DERIVATIVE

    def __init__(self, function: Any, variable: Any) -> None:
        super().__init__()
        self.variable = variable
        self.function = function
        self.expected = sp.diff(function, variable)
        self.solution = to_latex(simplified(self.expected))
        self.current: Any = None

    def _compare(self, index: int, expr: Any) -> None:
        if self.error is not None:
            return
        if self.current is None and equivalent(expr, self.function):
            self.record(index, StepStatus.SKIPPED, "function")
            return
        target = self.expected if self.current is None else self.current
        same = equivalent(target, expr)
        if same is None:
            self.record(index, StepStatus.UNSUPPORTED, "derivative")
        elif same:
            self.record(index, StepStatus.OK, "derivative")
        else:
            self.fail(
                index,
                "derivative",
                self._classify(target, expr),
                to_latex(simplified(target)),
                to_latex(expr),
            )
            return
        self.current = expr

    def _classify(self, target: Any, expr: Any) -> ErrorType:
        for mutated, error in expression_mutations(sp.expand(target)):
            if error is ErrorType.SIGN and equivalent(mutated, expr):
                return ErrorType.SIGN
        if equivalent(expr, -target):
            return ErrorType.SIGN
        return ErrorType.FORMULA

    def process(self, item: Item) -> None:
        statement = item.statement
        if isinstance(statement, Unparseable):
            self.record(item.index, StepStatus.UNPARSEABLE, "line")
            return
        parts, _ = _expression_parts(statement)
        if isinstance(statement, Equation) and statement.lhs.is_Symbol:
            parts = [statement.rhs]
        for part in parts:
            self._compare(item.index, part)
        if not parts:
            self.record(item.index, StepStatus.SKIPPED, "note")

    def finish(self) -> None:
        self.complete = self.current is not None
        self.final_answer = to_latex(self.current) if self.current is not None else None

    @property
    def variable_name(self) -> str | None:
        return str(self.variable)


def _symbols(parts: tuple[Any, ...] | list[Any]) -> set[Any]:
    found: set[Any] = set()
    for part in parts:
        found |= part.free_symbols
    return found


def _parts_of(statement: Statement) -> tuple[Any, ...]:
    match statement:
        case Equation(lhs=lhs, rhs=rhs):
            return (lhs, rhs)
        case Inequality(parts=parts) | Chain(parts=parts):
            return parts
        case Expression(expr=expr):
            return (expr,)
        case Disjunction(members=members) | System(members=members):
            return tuple(part for member in members for part in _parts_of(member))
    return ()


class SetChecker(Checker):
    def __init__(self, task: Statement, variable: Any, *, inequality: bool) -> None:
        super().__init__()
        self.kind = ProblemKind.INEQUALITY if inequality else ProblemKind.EQUATION
        self.variable = variable
        self.inequality = inequality
        self.domain = joint_domain(_parts_of(task), variable)
        task_set = self._set_of(task)
        if task_set is None:
            raise Unsupported
        self.truth = restrict(task_set, self.domain)
        self.current: Any = task_set
        self.solution = self._latex(self.truth)
        self.current_statement: Statement | None = task
        self.last_equation: Equation | None = task if isinstance(task, Equation) else None
        self.aux: Any = critical_points(_parts_of(task), variable) if inequality else None
        self.quadratics: list[tuple[Any, Any, Any]] = []
        self.loose: Any = sp.EmptySet
        self.run: list[tuple[int, Any]] = []
        self.answer: tuple[int, Any] | None = None
        self.rejected: list[Any] = []
        self.answer_last = False
        self.chain_value: Any = None
        self.excluded = self._excluded_roots(task)
        self._remember(task)

    @property
    def variable_name(self) -> str | None:
        return str(self.variable)

    def _excluded_roots(self, task: Statement) -> list[Any]:
        if not isinstance(task, Equation):
            return []
        numerator, _ = sp.fraction(sp.together(task.lhs - task.rhs))
        found = limited(lambda: sp.solveset(numerator, self.variable, sp.Reals), 0.4, None)
        if found is None or not is_finite(found):
            return []
        return [value for value in finite_elements(found) if not contains(self.domain, value)]

    def _is_variable(self, symbol: Any) -> bool:
        return bool(symbol.is_Symbol) and base_name(symbol) == str(self.variable)

    def _set_of(self, statement: Statement) -> Any:
        match statement:
            case Equation(lhs=lhs, rhs=rhs):
                if not _symbols([lhs, rhs]) <= {self.variable}:
                    return None
                return solve_equation(lhs, rhs, self.variable)
            case Inequality(parts=parts, ops=ops):
                if not _symbols(parts) <= {self.variable}:
                    return None
                return solve_inequality(parts, ops, self.variable)
            case Disjunction(members=members):
                result: Any = sp.EmptySet
                for member in members:
                    part = self._set_of(member)
                    if part is None:
                        return None
                    result = result.union(part)
                return result
            case System(members=members):
                combined: Any = sp.Reals
                for member in members:
                    part = self._set_of(member)
                    if part is None:
                        return None
                    combined = combined.intersect(part)
                return combined
            case Answer(values=values, variable=variable):
                if variable is not None and not self._is_variable(variable):
                    return None
                return values
        return None

    def _remember(self, statement: Statement) -> None:
        if isinstance(statement, Equation):
            self.last_equation = statement
        parts = _parts_of(statement)
        if len(parts) != 2 or not isinstance(statement, Equation | Inequality):
            return
        expr = parts[0] - parts[1]
        poly = limited(lambda: sp.Poly(sp.expand(expr), self.variable), 0.3, None)
        if poly is not None and poly.degree() == 2 and _symbols([expr]) == {self.variable}:
            a, b, c = poly.all_coeffs()
            self.quadratics.append((a, b, c))
        if expr.has(sp.Pow) and any(
            power.exp.is_Rational and not power.exp.is_Integer for power in expr.atoms(sp.Pow)
        ):
            squared = limited(
                lambda: solve_equation(
                    sp.expand(parts[0] ** 2), sp.expand(parts[1] ** 2), self.variable
                ),
                0.6,
                None,
            )
            if squared is not None and is_finite(squared):
                self.loose = self.loose.union(squared)

    def _quadratic(self) -> tuple[Any, Any, Any] | None:
        return self.quadratics[-1] if self.quadratics else None

    def _latex(self, values: Any) -> str:
        return answer_latex(values, self.variable)

    def process(self, item: Item) -> None:
        statement = item.statement
        index = item.index
        if self.run and not self._continues_run(statement):
            self._flush_run()
            if self.error is not None:
                return
        match statement:
            case Unparseable():
                self.record(index, StepStatus.UNPARSEABLE, "line")
            case Note():
                self._note(index, statement)
            case Expression():
                self._expression(index, statement)
            case Chain():
                self._chain(index, statement)
            case Equation():
                self._equation(index, statement)
            case Inequality():
                self._inequality(index, statement)
            case Disjunction():
                self._disjunction(index, statement)
            case System():
                self._system(index, statement)
            case Answer():
                self._answer(index, statement)

    def _continues_run(self, statement: Statement) -> bool:
        if isinstance(statement, Equation | Chain):
            return self._assignment_target(statement) is not None
        return isinstance(statement, Answer) and not statement.explicit

    def _assignment_target(self, statement: Equation | Chain) -> Any:
        parts = _parts_of(statement)
        if isinstance(statement, Equation):
            ops: tuple[Op, ...] = (Op.EQ,)
            raws = (statement.raw_lhs, statement.raw_rhs)
        else:
            ops, raws = statement.ops, statement.raw
        if not ops or any(op is not Op.EQ for op in ops):
            return None
        head = parts[0]
        if self._is_variable(raws[0]) and not _symbols(parts[1:]) & {self.variable, head}:
            numeric = [part for part in parts[1:] if not part.free_symbols]
            return numeric or None
        if len(parts) == 2 and self._is_variable(raws[1]) and not parts[0].free_symbols:
            return [parts[0]]
        return None

    def _note(self, index: int, note: Note) -> None:
        if note.kind is NoteKind.REJECT and note.inner is not None:
            rejected: list[Any] = []
            if isinstance(note.inner, Equation | Chain):
                rejected = self._assignment_target(note.inner) or []
            elif isinstance(note.inner, Answer) and is_finite(note.inner.values):
                rejected = finite_elements(note.inner.values)
            self.rejected.extend(value for value in rejected[-1:])
            if self.answer is not None and rejected:
                answer_index, values = self.answer
                self.answer = (answer_index, difference(values, sp.FiniteSet(*rejected[-1:])))
        self.record(index, StepStatus.SKIPPED, "note")

    def _expression(self, index: int, expression: Expression) -> None:
        if expression.continuation and self.chain_value is not None:
            self._numeric_chain(index, [self.chain_value, expression.expr], [Op.EQ])
            return
        self.record(index, StepStatus.SKIPPED, "expression")

    def _numeric_chain(
        self, index: int, parts: list[Any], ops: list[Op], *, record: bool = True
    ) -> bool:
        for left, op, right in zip(parts, ops, parts[1:], strict=False):
            if left.free_symbols or right.free_symbols:
                continue
            holds = _relation_holds(left, op, right)
            if holds is False:
                expected = to_latex(sp.nsimplify(left)) if op is Op.EQ else None
                self.fail(index, "arithmetic", ErrorType.ARITHMETIC, expected, to_latex(right))
                return False
        numeric = [part for part in parts if not part.free_symbols]
        equalities = all(op is Op.EQ for op in ops)
        self.chain_value = numeric[-1] if numeric and equalities else None
        if record:
            self.record(index, StepStatus.OK, "arithmetic")
        return True

    def _chain(self, index: int, chain: Chain) -> None:
        parts = list(chain.parts)
        raws = list(chain.raw)
        ops = list(chain.ops)
        if chain.continuation and self.chain_value is not None:
            parts = [self.chain_value, *parts]
            raws = [self.chain_value, *raws]
            ops = [Op.EQ, *ops]
        head = parts[0]
        if head.is_Symbol and base_name(head) == "d" and str(self.variable) != "d":
            self._discriminant(index, parts, ops)
            return
        values = self._assignment_target(chain)
        if values is not None:
            if self._numeric_chain(index, values, [Op.EQ] * (len(values) - 1), record=False):
                self._assign(index, values[-1])
            return
        if not _symbols(parts):
            self._numeric_chain(index, parts, ops)
            return
        if all(op is Op.EQ for op in ops) and _symbols(parts) <= {self.variable}:
            for position in range(len(parts) - 2):
                before, after = parts[position], parts[position + 1]
                if equivalent(before, after) is False:
                    self.fail(
                        index,
                        "expression",
                        classify_expression(raws[position], before, after),
                        to_latex(simplified(before)),
                        to_latex(after),
                    )
                    return
            self._equation(index, Equation(parts[-2], parts[-1], raws[-2], raws[-1]))
            return
        self.record(index, StepStatus.UNSUPPORTED, "chain")

    def _equation(self, index: int, equation: Equation) -> None:
        head = equation.lhs
        if head.is_Symbol and base_name(head) == "d" and str(self.variable) != "d":
            self._discriminant(index, [equation.lhs, equation.rhs], [Op.EQ])
            return
        values = self._assignment_target(equation)
        if values is not None:
            self._assign(index, values[-1])
            return
        symbols = _symbols([equation.lhs, equation.rhs])
        if not symbols:
            self._numeric_chain(index, [equation.lhs, equation.rhs], [Op.EQ])
            return
        if (
            symbols
            and all(self._is_variable(symbol) for symbol in symbols)
            and (self.variable not in symbols)
        ):
            self._vieta(index, [equation])
            return
        if symbols != {self.variable}:
            self.record(index, StepStatus.UNSUPPORTED, "equation")
            return
        new_set = self._safe_set(index, equation)
        if new_set is None:
            return
        if self.inequality:
            self._aux_transition(index, equation, new_set)
        else:
            self._transition(index, equation, new_set)

    def _safe_set(self, index: int, statement: Statement) -> Any:
        try:
            result = self._set_of(statement)
        except Unsupported:
            result = None
        if result is None:
            self.record(index, StepStatus.UNSUPPORTED, "statement")
        return result

    def _inequality(self, index: int, inequality: Inequality) -> None:
        if not self.inequality or Op.NE in inequality.ops:
            self.record(index, StepStatus.SKIPPED, "condition")
            return
        head = inequality.parts[0]
        if head.is_Symbol and base_name(head) == "d" and str(self.variable) != "d":
            self._discriminant(index, list(inequality.parts), list(inequality.ops))
            return
        if not _symbols(inequality.parts):
            self._numeric_chain(index, list(inequality.parts), list(inequality.ops))
            return
        new_set = self._safe_set(index, inequality)
        if new_set is None:
            return
        self._transition(index, inequality, new_set)
        if self.error is None:
            self.aux = critical_points(inequality.parts, self.variable)
            solved = (
                all(part == self.variable or not part.free_symbols for part in inequality.parts)
                and sum(part == self.variable for part in inequality.parts) == 1
            )
            if solved:
                self.answer = (index, new_set)
                self.answer_last = True

    def _disjunction(self, index: int, disjunction: Disjunction) -> None:
        new_set = self._safe_set(index, disjunction)
        if new_set is None:
            return
        if self.inequality:
            self._aux_transition(index, disjunction, new_set)
            return
        self._transition(index, disjunction, new_set)
        solved = all(
            isinstance(member, Equation) and self._assignment_target(member) is not None
            for member in disjunction.members
        )
        if solved and self.error is None:
            self.answer = (index, new_set)
            self.answer_last = True

    def _system(self, index: int, system: System) -> None:
        symbols = _symbols(_parts_of(system))
        if (
            symbols
            and all(self._is_variable(symbol) for symbol in symbols)
            and (self.variable not in symbols)
        ):
            self._vieta(index, [m for m in system.members if isinstance(m, Equation)])
            return
        new_set = self._safe_set(index, system)
        if new_set is None:
            return
        self._transition(index, system, new_set)

    def _answer(self, index: int, answer: Answer) -> None:
        if answer.points or answer.variables:
            self.record(index, StepStatus.UNSUPPORTED, "answer")
            return
        if answer.variable is not None and not self._is_variable(answer.variable):
            self.record(index, StepStatus.SKIPPED, "answer")
            return
        values = answer.values
        if not answer.explicit and is_finite(values):
            for value in finite_elements(values):
                self._assign(index, value)
                if self.error is not None:
                    return
            return
        if self.run:
            self._flush_run()
        self._transition(index, answer, values)
        if self.error is None:
            self.answer = (index, values)
            self.answer_last = True

    def _assign(self, index: int, value: Any) -> None:
        target = self.aux if self.inequality else self.current
        acceptable = (
            not is_finite(target)
            or contains(target, value)
            or not contains(self.domain, value)
            or contains(self.loose, value)
            or any(_numbers_equal(value, item) for item in self.rejected)
        )
        if not acceptable:
            self.fail(
                index,
                "root",
                self._classify_values(target, sp.FiniteSet(value)),
                self._latex(restrict(target, self.domain)),
                f"{to_latex(self.variable)} = {to_latex(value)}",
            )
            return
        self.run.append((index, value))
        self.record(index, StepStatus.OK, "root")

    def _flush_run(self) -> None:
        run, self.run = self.run, []
        if not run or self.error is not None:
            return
        values = sp.FiniteSet(*[value for _, value in run])
        last_index = run[-1][0]
        if self.inequality:
            return
        target = restrict(self.current, self.domain)
        missing = difference(target, values)
        if is_finite(target) and finite_elements(missing):
            error = (
                ErrorType.DIVISION_BY_VARIABLE
                if self._divided(finite_elements(missing))
                else ErrorType.LOST_ROOT
            )
            self.fail(last_index, "roots", error, self._latex(target), self._latex(values))
            return
        self.current = values
        self.current_statement = None
        self.answer = (last_index, values)
        self.answer_last = True

    def _divided(self, missing: list[Any]) -> bool:
        equation = self.last_equation
        if equation is None or not (
            equation.lhs.has(self.variable) and equation.rhs.has(self.variable)
        ):
            return False
        for root in missing:
            left = equation.lhs.xreplace({self.variable: root})
            right = equation.rhs.xreplace({self.variable: root})
            if not (_numbers_equal(left, 0) and _numbers_equal(right, 0)):
                return False
        return True

    def _transition(self, index: int, statement: Statement, new_set: Any) -> None:
        previous = restrict(self.current, self.domain)
        current = restrict(new_set, self.domain)
        same = same_set(previous, current)
        if same is None:
            self.record(index, StepStatus.UNSUPPORTED, "transition")
        elif same:
            self.record(index, StepStatus.OK, "transition")
        elif subset(previous, current):
            self.record(index, StepStatus.CONSEQUENCE, "transition")
        elif subset(current, previous) and subset(self.truth, current):
            self.record(index, StepStatus.OK, "transition")
        else:
            outside = [
                value
                for value in finite_elements(new_set)
                if is_finite(new_set)
                if not contains(self.domain, value)
            ]
            error = (
                ErrorType.DOMAIN
                if outside and isinstance(statement, Answer)
                else self._classify_transition(statement, previous, current)
            )
            expected = self._latex(previous)
            got = self._latex(current)
            self.fail(index, "transition", error, expected, got)
            return
        self.current = new_set
        self.current_statement = statement
        self.answer_last = False
        self._remember(statement)

    def _aux_transition(self, index: int, statement: Statement, new_set: Any) -> None:
        target = self.aux if self.aux is not None else sp.EmptySet
        accepted = same_set(new_set, target) or subset(new_set, target)
        if accepted is None:
            self.record(index, StepStatus.UNSUPPORTED, "zeros")
            return
        if not accepted:
            error = self._classify_values(target, new_set)
            self.fail(index, "zeros", error, self._latex(target), self._latex(new_set))
            return
        self.aux = new_set
        self.record(index, StepStatus.OK, "zeros")
        self._remember(statement)

    def _classify_transition(self, statement: Statement, previous: Any, current: Any) -> ErrorType:
        before = self.current_statement
        if isinstance(statement, Equation) and self._wrong_factoring(statement):
            return ErrorType.FACTORING
        if isinstance(before, Equation) and isinstance(statement, Equation):
            found = self._match_equation(before, statement)
            if found is not None:
                return found
        if isinstance(before, Inequality) and isinstance(statement, Inequality):
            found = self._match_inequality(before, statement, previous)
            if found is not None:
                return found
        missing = finite_elements(difference(previous, current)) if is_finite(previous) else []
        if is_finite(current) and is_finite(previous) and missing and subset(current, previous):
            return ErrorType.DIVISION_BY_VARIABLE if self._divided(missing) else ErrorType.LOST_ROOT
        return self._classify_values(previous, current)

    def _wrong_factoring(self, statement: Equation) -> bool:

        for whole, product in (
            (statement.raw_lhs, statement.raw_rhs),
            (statement.raw_rhs, statement.raw_lhs),
        ):
            if not isinstance(product, sp.Mul) or isinstance(whole, sp.Mul):
                continue
            if not whole.has(self.variable) or not whole.is_polynomial(self.variable):
                continue
            factors = [f for f in product.args if f.has(self.variable)]
            if not all(f.is_polynomial(self.variable) for f in factors):
                continue
            if len(factors) >= 2 and sp.expand(whole - product) != 0:
                return True
        return False

    def _match_equation(self, before: Equation, after: Equation) -> ErrorType | None:
        target = after.lhs - after.rhs
        for candidate, error in equation_mutations(before.raw_lhs, before.raw_rhs)[
            :MAX_CLASSIFY_CANDIDATES
        ]:
            if proportional(target, candidate, self.variable):
                return error
        for candidate in transfer_mutations(before.raw_lhs, before.raw_rhs)[:6]:
            try:
                mutated = solve_equation(candidate, sp.Integer(0), self.variable)
                actual = solve_equation(after.lhs, after.rhs, self.variable)
            except Unsupported:
                continue
            if same_set(restrict(mutated, self.domain), restrict(actual, self.domain)):
                return ErrorType.SIGN
        return None

    def _match_inequality(
        self, before: Inequality, after: Inequality, previous: Any
    ) -> ErrorType | None:
        if len(after.ops) == 1 and after.ops[0] in INEQUALITY_OPS:
            try:
                flipped = solve_inequality(after.parts, (FLIPPED[after.ops[0]],), self.variable)
            except Unsupported:
                flipped = None
            if flipped is not None and same_set(restrict(flipped, self.domain), previous):
                return ErrorType.INEQUALITY_FLIP
        if len(before.parts) == 2 and len(after.parts) == 2:
            actual = after.parts[0] - after.parts[1]
            for candidate in transfer_mutations(before.raw[0], before.raw[1])[:8]:
                if proportional(actual, candidate, self.variable):
                    return ErrorType.SIGN
                if proportional(actual, -candidate, self.variable):
                    return ErrorType.SIGN
        return None

    def _formula_variants(self) -> list[tuple[Any, ErrorType]]:
        quadratic = self._quadratic()
        if quadratic is None:
            return []
        a, b, c = quadratic
        discriminant = b**2 - 4 * a * c
        if discriminant.is_negative:
            return []
        root = sp.sqrt(discriminant)
        variants: list[tuple[Any, ErrorType]] = []
        for sign in (1, -1):
            variants.append(((b + sign * root) / (2 * a), ErrorType.SIGN))
            variants.append(((-b + sign * root) / a, ErrorType.FORMULA))
            variants.append(((-b + sign * discriminant) / (2 * a), ErrorType.FORMULA))
            variants.append((-b + sign * root / (2 * a), ErrorType.FORMULA))
            variants.append(((-b + sign * root) / 2, ErrorType.FORMULA))
        return variants

    def _classify_values(self, previous: Any, current: Any) -> ErrorType:
        if not (is_finite(previous) and is_finite(current)):
            if self.inequality:
                return self._classify_intervals(previous, current)
            return ErrorType.OTHER
        old = finite_elements(previous)
        new = finite_elements(current)
        extra = [value for value in new if not any(_numbers_equal(value, item) for item in old)]
        missing = [value for value in old if not any(_numbers_equal(value, item) for item in new)]
        known = [*old, *self.excluded]
        if extra and all(any(_numbers_equal(-value, item) for item in known) for value in extra):
            return ErrorType.SIGN
        for value in extra:
            for variant, error in self._formula_variants():
                if _numbers_equal(value, variant):
                    return error
        if not extra and missing:
            return ErrorType.LOST_ROOT
        return ErrorType.ARITHMETIC

    def _classify_intervals(self, previous: Any, current: Any) -> ErrorType:
        complement = difference(self.domain, previous)
        if same_interior(complement, current):
            boundary = limited(lambda: previous.boundary, 0.3, None)
            single = boundary is not None and len(finite_elements(boundary)) == 1
            return ErrorType.INEQUALITY_FLIP if single else ErrorType.SIGN
        if same_interior(previous, current):
            return ErrorType.OTHER
        return ErrorType.ARITHMETIC

    def _discriminant(self, index: int, parts: list[Any], ops: list[Op]) -> None:
        quadratic = self._quadratic()
        numeric = [part for part in parts[1:] if not part.free_symbols]
        if quadratic is None or not numeric:
            self.record(index, StepStatus.SKIPPED, "discriminant")
            return
        a, b, c = quadratic
        expected = b**2 - 4 * a * c
        claimed = numeric[0]
        accepted: list[Any] = []
        for aa, bb, cc in self.quadratics:
            value = bb**2 - 4 * aa * cc
            accepted += [value, value / 4]
        if not any(_numbers_equal(claimed, value) for value in accepted):
            variants = [
                b**2 + 4 * a * c,
                b**2 - 2 * a * c,
                b - 4 * a * c,
                -(b**2) - 4 * a * c,
                b**2 - 4 * c,
                b**2 - 4 * a,
            ]
            error = (
                ErrorType.FORMULA
                if any(_numbers_equal(claimed, variant) for variant in variants)
                else ErrorType.ARITHMETIC
            )
            self.fail(
                index,
                "discriminant",
                error,
                f"D = {to_latex(expected)}",
                f"D = {to_latex(claimed)}",
            )
            return
        self._numeric_chain(index, parts, ops)

    def _vieta(self, index: int, members: list[Equation]) -> None:
        quadratic = self._quadratic()
        if quadratic is None or not members:
            self.record(index, StepStatus.SKIPPED, "vieta")
            return
        a, b, c = quadratic
        unknown = sp.Symbol("t")
        found = sp.roots(sp.Poly(a * unknown**2 + b * unknown + c, unknown))
        roots = [root for root, count in found.items() for _ in range(count)]
        if len(roots) != 2:
            self.record(index, StepStatus.UNSUPPORTED, "vieta")
            return
        names = sorted(_symbols(_parts_of(System(tuple(members)))), key=str)
        orders = [
            dict(zip(names, roots, strict=False)),
            dict(zip(names, roots[::-1], strict=False)),
        ]
        for member in members:
            expr = member.lhs - member.rhs
            if not any(_numbers_equal(expr.xreplace(order), 0) for order in orders):
                expected = f"x_1 + x_2 = {to_latex(-b / a)},\\ x_1 x_2 = {to_latex(c / a)}"
                got = f"{to_latex(member.lhs)} = {to_latex(member.rhs)}"
                self.fail(index, "vieta", ErrorType.FORMULA, expected, got)
                return
        self.record(index, StepStatus.OK, "vieta")

    def finish(self) -> None:
        if self.run:
            self._flush_run()
        if self.error is not None:
            return
        if self.answer is None or not self.answer_last:
            return
        index, values = self.answer
        self.final_answer = self._latex(values)
        same = same_set(values, self.truth)
        if same is None:
            return
        if same:
            self.complete = True
            return
        error = self._classify_final(values)
        self.fail(index, "answer", error, self.solution, self.final_answer)

    def _classify_final(self, values: Any) -> ErrorType:
        if not (is_finite(values) and is_finite(self.truth)):
            return self._classify_intervals(self.truth, values)
        extra = finite_elements(difference(values, self.truth))
        missing = finite_elements(difference(self.truth, values))
        if extra and all(not contains(self.domain, value) for value in extra):
            return ErrorType.DOMAIN
        if extra and not missing:
            return ErrorType.EXTRANEOUS_ROOT
        if missing and not extra:
            return ErrorType.DIVISION_BY_VARIABLE if self._divided(missing) else ErrorType.LOST_ROOT
        return self._classify_values(self.truth, values)


class SystemChecker(Checker):
    kind = ProblemKind.SYSTEM

    def __init__(self, task: System) -> None:
        super().__init__()
        equations = [member for member in task.members if isinstance(member, Equation)]
        if len(equations) != len(task.members):
            raise Unsupported
        self.variables = sorted(_symbols(_parts_of(task)), key=str)
        if len(self.variables) < 2 or len(self.variables) > 3:
            raise Unsupported
        self.truth = solve_system([(e.lhs, e.rhs) for e in equations], self.variables)
        self.history: list[Equation] = list(equations)
        self.values: dict[Any, Any] = {}
        self.solution = self._points_latex(self.truth)
        self.answer: tuple[int, list[tuple[Any, ...]]] | None = None
        self.answer_last = False

    @property
    def variable_name(self) -> str | None:
        return ", ".join(str(variable) for variable in self.variables)

    def _holds(self, equation: Equation) -> bool:
        expr = equation.lhs - equation.rhs
        return all(
            _numbers_equal(expr.xreplace(dict(zip(self.variables, point, strict=True))), 0)
            for point in self.truth
        )

    def _points_latex(self, points: list[tuple[Any, ...]]) -> str:
        if not points:
            return r"\varnothing"
        return "; ".join(
            "(" + "; ".join(to_latex(value) for value in point) + ")" for point in points
        )

    def _same_points(self, first: list[tuple[Any, ...]], second: list[tuple[Any, ...]]) -> bool:
        if len(first) != len(second):
            return False
        return all(
            any(all(_numbers_equal(a, b) for a, b in zip(p, q, strict=True)) for q in second)
            for p in first
        )

    def _classify(self, equation: Equation) -> ErrorType:
        target = equation.lhs - equation.rhs
        for previous in self.history[-4:]:
            for candidate in transfer_mutations(previous.raw_lhs, previous.raw_rhs):
                for variable in self.variables:
                    if target.has(variable) and proportional(target, candidate, variable):
                        return ErrorType.SIGN
            for candidate, error in equation_mutations(previous.raw_lhs, previous.raw_rhs)[:20]:
                if equivalent(target, candidate):
                    return error
        return ErrorType.ARITHMETIC

    def _equation(self, index: int, equation: Equation) -> None:
        symbols = _symbols([equation.lhs, equation.rhs])
        if not symbols <= set(self.variables):
            self.record(index, StepStatus.UNSUPPORTED, "equation")
            return
        if not symbols:
            if _numbers_equal(equation.lhs, equation.rhs):
                self.record(index, StepStatus.OK, "arithmetic")
            else:
                self.fail(
                    index,
                    "arithmetic",
                    ErrorType.ARITHMETIC,
                    to_latex(equation.lhs),
                    to_latex(equation.rhs),
                )
            return
        solved = equation.lhs.is_Symbol and not equation.rhs.free_symbols
        if solved:
            candidates = [point[self.variables.index(equation.lhs)] for point in self.truth]
            if any(_numbers_equal(equation.rhs, value) for value in candidates) or not self.truth:
                self.values[equation.lhs] = equation.rhs
                self.record(index, StepStatus.OK, "value")
                self.answer_last = len(self.values) == len(self.variables)
                return
            error = (
                ErrorType.SIGN
                if any(_numbers_equal(-equation.rhs, value) for value in candidates)
                else self._classify(equation)
            )
            expected = "; ".join(f"{to_latex(equation.lhs)} = {to_latex(v)}" for v in candidates)
            self.fail(
                index,
                "value",
                error,
                expected,
                f"{to_latex(equation.lhs)} = {to_latex(equation.rhs)}",
            )
            return
        if self._holds(equation):
            self.history.append(equation)
            self.record(index, StepStatus.OK, "equation")
            self.answer_last = False
            return
        self.fail(
            index,
            "equation",
            self._classify(equation),
            self._points_latex(self.truth),
            f"{to_latex(equation.lhs)} = {to_latex(equation.rhs)}",
        )

    def process(self, item: Item) -> None:
        statement = item.statement
        index = item.index
        match statement:
            case Unparseable():
                self.record(index, StepStatus.UNPARSEABLE, "line")
            case Equation():
                self._equation(index, statement)
            case System(members=members) | Disjunction(members=members):
                for member in members:
                    if isinstance(member, Equation):
                        self._equation(index, member)
                    if self.error is not None:
                        return
            case Answer(points=points, variables=variables) if points:
                ordered = list(points)
                if variables:
                    order = [variables.index(v) if v in variables else -1 for v in self.variables]
                    if -1 in order:
                        self.record(index, StepStatus.UNSUPPORTED, "answer")
                        return
                    ordered = [tuple(point[k] for k in order) for point in points]
                self.answer = (index, ordered)
                self.answer_last = True
                self.record(index, StepStatus.OK, "answer")
            case Chain(parts=parts, ops=ops) if not _symbols(parts):
                for left, op, right in zip(parts, ops, parts[1:], strict=False):
                    if _relation_holds(left, op, right) is False:
                        self.fail(
                            index,
                            "arithmetic",
                            ErrorType.ARITHMETIC,
                            to_latex(left),
                            to_latex(right),
                        )
                        return
                self.record(index, StepStatus.OK, "arithmetic")
            case _:
                self.record(index, StepStatus.SKIPPED, "note")

    def finish(self) -> None:
        if self.error is not None:
            return
        points: list[tuple[Any, ...]] | None = None
        index = -1
        if self.answer is not None and self.answer_last:
            index, points = self.answer
        elif self.answer_last and len(self.values) == len(self.variables):
            points = [tuple(self.values[variable] for variable in self.variables)]
            index = max(step.index for step in self.steps if step.kind == "value")
        if points is None:
            return
        self.final_answer = self._points_latex(points)
        if self._same_points(points, self.truth):
            self.complete = True
            return
        self.fail(index, "answer", self._classify_points(points), self.solution, self.final_answer)

    def _classify_points(self, points: list[tuple[Any, ...]]) -> ErrorType:
        if len(points) != 1 or len(self.truth) != 1:
            return ErrorType.ARITHMETIC
        given, truth = points[0], self.truth[0]
        if self._same_points([tuple(reversed(given))], [truth]):
            return ErrorType.OTHER
        matches = [
            _numbers_equal(a, b) or _numbers_equal(-a, b) for a, b in zip(given, truth, strict=True)
        ]
        if all(matches):
            return ErrorType.SIGN
        return ErrorType.ARITHMETIC
