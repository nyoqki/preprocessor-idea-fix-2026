from dataclasses import dataclass
from enum import StrEnum

from yasno.math.errors import ErrorType


class Status(StrEnum):
    CORRECT = "correct"
    ERROR = "error"
    INCOMPLETE = "incomplete"
    UNPARSEABLE = "unparseable"
    UNSUPPORTED = "unsupported"


class ProblemKind(StrEnum):
    EXPRESSION = "expression"
    EQUATION = "equation"
    INEQUALITY = "inequality"
    SYSTEM = "system"
    DERIVATIVE = "derivative"
    UNKNOWN = "unknown"


class StepStatus(StrEnum):
    OK = "ok"
    CONSEQUENCE = "consequence"
    ERROR = "error"
    SKIPPED = "skipped"
    UNPARSEABLE = "unparseable"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class StepCheck:
    index: int
    status: StepStatus
    kind: str
    error_type: ErrorType | None = None
    expected: str | None = None
    got: str | None = None


@dataclass(frozen=True, slots=True)
class Verification:
    status: Status
    problem_kind: ProblemKind
    first_error_step: int | None = None
    error_type: ErrorType | None = None
    expected: str | None = None
    got: str | None = None
    steps: tuple[StepCheck, ...] = ()
    final_answer: str | None = None
    unparseable_step: int | None = None
    solution: str | None = None
    variable: str | None = None

    @property
    def is_correct(self) -> bool:
        return self.status is Status.CORRECT
