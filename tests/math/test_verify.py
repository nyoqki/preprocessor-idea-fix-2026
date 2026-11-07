import multiprocessing
import time
from concurrent.futures import ProcessPoolExecutor

import pytest

from yasno.math.errors import ErrorType
from yasno.math.verification import ProblemKind, Status
from yasno.math.verify import verify_solution

CORRECT_SOLUTIONS = [
    pytest.param(["5x - 3 = 2x + 9", "5x - 2x = 9 + 3", "3x = 12", "x = 4"], None, id="linear"),
    pytest.param(
        [r"\frac{x}{2} + \frac{x}{3} = 5", "3x + 2x = 30", "5x = 30", "x = 6"],
        None,
        id="linear-fractions",
    ),
    pytest.param(
        [
            "x^2 - 5x + 6 = 0",
            r"D = b^2 - 4ac = (-5)^2 - 4 \cdot 1 \cdot 6 = 1",
            r"x_1 = \frac{5+1}{2} = 3",
            r"x_2 = \frac{5-1}{2} = 2",
            "Ответ: 2; 3",
        ],
        None,
        id="quadratic-discriminant",
    ),
    pytest.param(
        [
            "2x^2 + 3x - 2 = 0",
            "D = 9 + 16 = 25",
            r"x_{1,2} = \frac{-3 \pm 5}{4}",
            "x_1 = 0,5; x_2 = -2",
        ],
        None,
        id="quadratic-plus-minus",
    ),
    pytest.param(
        ["x^2 - 5x + 6 = 0", r"x_1 + x_2 = 5, x_1 \cdot x_2 = 6", "x_1 = 2, x_2 = 3"],
        None,
        id="quadratic-vieta",
    ),
    pytest.param(
        ["x^2 = 3x", "x^2 - 3x = 0", "x(x-3) = 0", "x = 0 или x - 3 = 0", "x = 0 или x = 3"],
        None,
        id="factoring",
    ),
    pytest.param(
        [
            r"\frac{x^2}{x-2} = \frac{4}{x-2}",
            "ОДЗ: x ≠ 2",
            "x^2 = 4",
            "x = ±2",
            "x = 2 не входит в ОДЗ",
            "Ответ: -2",
        ],
        None,
        id="rational-with-domain",
    ),
    pytest.param(
        ["x² + 4 = 0", "x² = −4", "корней нет"],
        None,
        id="no-roots-phrase",
    ),
    pytest.param(
        ["-2x + 4 > 0", "-2x > -4", "x < 2", r"Ответ: x \in (-\infty; 2)"],
        None,
        id="linear-inequality",
    ),
    pytest.param(
        ["-1 < 2x + 1 < 5", "-2 < 2x < 4", "-1 < x < 2"],
        None,
        id="double-inequality",
    ),
    pytest.param(
        [
            "x^2 - 5x + 6 < 0",
            "x^2 - 5x + 6 = 0",
            "D = 1",
            "x_1 = 2, x_2 = 3",
            "+ − +",
            "Ответ: x ∈ (2; 3)",
        ],
        None,
        id="interval-method",
    ),
    pytest.param(
        [r"\frac{x-1}{x+2} \ge 0", r"x \in (-\infty; -2) \cup [1; +\infty)"],
        None,
        id="rational-inequality",
    ),
    pytest.param(["x^2 + 1 < 0", "Ответ: нет решений"], None, id="empty-inequality"),
    pytest.param(["2^{x+1} = 8", "2^{x+1} = 2^3", "x + 1 = 3", "x = 2"], None, id="exponential"),
    pytest.param(
        [
            r"\log_2(x) + \log_2(x-2) = 3",
            r"\log_2(x(x-2)) = 3",
            "x^2 - 2x = 8",
            "x^2 - 2x - 8 = 0",
            "x_1 = 4, x_2 = -2",
            "x = -2 не удовлетворяет ОДЗ",
            "Ответ: 4",
        ],
        None,
        id="logarithmic",
    ),
    pytest.param(
        [
            r"\sqrt{x+2} = x",
            "x + 2 = x^2",
            "x^2 - x - 2 = 0",
            "x_1 = 2, x_2 = -1",
            "x = -1 — посторонний корень",
            "Ответ: 2",
        ],
        None,
        id="irrational",
    ),
    pytest.param(
        ["(a-b)^2 - a^2", "= a^2 - 2ab + b^2 - a^2", "= b^2 - 2ab"], None, id="simplification"
    ),
    pytest.param(
        [r"\frac{x^2-9}{x+3}", r"= \frac{(x-3)(x+3)}{x+3}", "= x - 3"], None, id="reduce-fraction"
    ),
    pytest.param(
        [r"\frac{1}{2} + \frac{1}{3}", r"= \frac{3}{6} + \frac{2}{6} = \frac{5}{6}"],
        None,
        id="fractions",
    ),
    pytest.param(["3x = 12", "x = 4"], "Решите уравнение 3x + 5 = 17", id="task-given"),
    pytest.param(
        [r"\begin{cases} x+y=5 \\ x-y=1 \end{cases}", "2x = 6", "x = 3", "y = 2", "Ответ: (3; 2)"],
        None,
        id="system",
    ),
    pytest.param(["0,5x + 1,5 = 2", "0,5x = 0,5", "x = 1"], None, id="decimal-comma"),
    pytest.param(["1) 2x − 3 = 5 | +3", "2x = 8 | :2", "x = 4."], None, id="ocr-noise"),
    pytest.param(["f'(x) = 3x^2 + 2"], "Найдите производную f(x) = x^3 + 2x", id="derivative"),
]


@pytest.mark.parametrize(("lines", "task"), CORRECT_SOLUTIONS)
def test_correct_solutions(lines: list[str], task: str | None) -> None:
    result = verify_solution(lines, task)
    assert result.status is Status.CORRECT, result
    assert result.first_error_step is None
    assert result.final_answer


MISTAKES = [
    pytest.param(
        ["5x - 3 = 2x + 9", "5x - 2x = 9 - 3", "3x = 6", "x = 2"],
        1,
        ErrorType.SIGN,
        id="sign-when-transferring",
    ),
    pytest.param(["3x = 12", "x = 3"], 1, ErrorType.ARITHMETIC, id="arithmetic"),
    pytest.param(
        ["x^2 - 5x + 6 = 0", "D = 25 + 24 = 49", r"x_1 = \frac{5+7}{2} = 6"],
        1,
        ErrorType.FORMULA,
        id="wrong-discriminant",
    ),
    pytest.param(
        ["x^2 - 5x + 6 = 0", "D = 1", r"x_1 = \frac{-5+1}{2} = -2"],
        2,
        ErrorType.SIGN,
        id="quadratic-formula-sign",
    ),
    pytest.param(
        ["x^2 - 5x + 6 = 0", "x_1 + x_2 = -5, x_1 x_2 = 6", "x_1 = -2, x_2 = -3"],
        1,
        ErrorType.FORMULA,
        id="vieta-sign",
    ),
    pytest.param(
        ["x^2 - 5x + 6 = 0", "(x+2)(x+3) = 0", "x = -2 или x = -3"],
        1,
        ErrorType.SIGN,
        id="roots-negated",
    ),
    pytest.param(
        ["(x-3)^2 = x^2 - 15", "x^2 - 9 = x^2 - 15"],
        1,
        ErrorType.DISTRIBUTION,
        id="square-of-difference",
    ),
    pytest.param(
        ["(a-b)^2 - a^2", "= a^2 - b^2 - a^2", "= -b^2"],
        1,
        ErrorType.DISTRIBUTION,
        id="square-in-expression",
    ),
    pytest.param(
        ["5 - (x - 3)", "= 5 - x - 3", "= 2 - x"],
        1,
        ErrorType.DISTRIBUTION,
        id="minus-before-brackets",
    ),
    pytest.param(["x^2 = 3x", "x = 3"], 1, ErrorType.DIVISION_BY_VARIABLE, id="lost-zero"),
    pytest.param(
        ["x^2 = 3x", r"\frac{x^2}{x} = 3", "x = 3"],
        1,
        ErrorType.DIVISION_BY_VARIABLE,
        id="explicit-division",
    ),
    pytest.param(["x^2 = 9", "x = 3"], 1, ErrorType.LOST_ROOT, id="lost-negative-root"),
    pytest.param(["-2x + 4 > 0", "-2x > -4", "x > 2"], 2, ErrorType.INEQUALITY_FLIP, id="no-flip"),
    pytest.param(
        ["x^2 - 5x + 6 < 0", "(x-2)(x-3) < 0", "Ответ: x ∈ (−∞; 2) ∪ (3; +∞)"],
        2,
        ErrorType.SIGN,
        id="wrong-intervals",
    ),
    pytest.param(
        [r"\frac{x^2}{x-2} = \frac{4}{x-2}", "x^2 = 4", "x = 2, x = -2", "Ответ: -2; 2"],
        3,
        ErrorType.DOMAIN,
        id="root-zeroes-denominator",
    ),
    pytest.param(
        [r"\sqrt{x+2} = x", "x + 2 = x^2", "x^2 - x - 2 = 0", "x_1 = 2, x_2 = -1", "Ответ: -1; 2"],
        4,
        ErrorType.EXTRANEOUS_ROOT,
        id="extraneous-after-squaring",
    ),
    pytest.param(["x^2 \\cdot x^3", "= x^6"], 1, ErrorType.POWERS, id="powers"),
    pytest.param(
        [r"\frac{1}{2} + \frac{1}{3}", r"= \frac{2}{5}"], 1, ErrorType.FRACTIONS, id="fractions"
    ),
    pytest.param(
        [r"\begin{cases} x+y=5 \\ x-y=1 \end{cases}", "2x = 4", "x = 2"],
        1,
        ErrorType.ARITHMETIC,
        id="system-arithmetic",
    ),
    pytest.param(
        [r"\begin{cases} x+y=5 \\ x-y=1 \end{cases}", "Ответ: (2; 3)"],
        1,
        ErrorType.OTHER,
        id="system-swapped-coordinates",
    ),
    pytest.param(
        [r"\frac{x^2 - 7x + 6}{x - 1} = 0", "Ответ: -6; -1"],
        1,
        ErrorType.SIGN,
        id="rational-roots-negated",
    ),
    pytest.param(
        [r"\frac{x^2 - 7x + 6}{x - 1} = 0", "Ответ: 1; 6"],
        1,
        ErrorType.DOMAIN,
        id="rational-answer-outside-domain",
    ),
    pytest.param(
        ["-3x + 6 \\le 0", "Ответ: x \\in (-\\infty; 2]"],
        1,
        ErrorType.INEQUALITY_FLIP,
        id="inequality-answer-flipped",
    ),
]


@pytest.mark.parametrize(("lines", "step", "error"), MISTAKES)
def test_mistakes(lines: list[str], step: int, error: ErrorType) -> None:
    result = verify_solution(lines)
    assert result.status is Status.ERROR, result
    assert result.first_error_step == step
    assert result.error_type is error
    assert result.expected
    assert result.got


def test_first_error_step_is_zero_based_line_position() -> None:
    result = verify_solution(["", "5x - 3 = 2x + 9", "", "5x - 2x = 9 - 3"])
    assert result.first_error_step == 3


def test_error_in_first_line_against_task() -> None:
    result = verify_solution(["3x = 22", "x = 22/3"], "Решите уравнение 3x + 5 = 17")
    assert result.status is Status.ERROR
    assert result.first_error_step == 0


def test_incomplete_solution() -> None:
    result = verify_solution(["x^2 - 5x + 6 = 0", "D = 1"])
    assert result.status is Status.INCOMPLETE
    assert result.problem_kind is ProblemKind.EQUATION


def test_unparseable_solution() -> None:
    result = verify_solution(["@@ ## $$"])
    assert result.status is Status.UNPARSEABLE
    assert result.unparseable_step == 0


def test_unsupported_trigonometry() -> None:
    assert verify_solution([r"\sin x = 0", r"x = \pi n"]).status is Status.UNSUPPORTED


def test_solution_and_kind_are_reported() -> None:
    result = verify_solution(["x^2 - 4 < 0", "Ответ: x ∈ (-2; 2)"])
    assert result.problem_kind is ProblemKind.INEQUALITY
    assert result.solution == r"x \in (-2; 2)"
    assert result.variable == "x"


def test_typical_solution_is_fast() -> None:
    lines = [
        "x^2 - 5x + 6 = 0",
        "D = 25 - 24 = 1",
        r"x_1 = \frac{5+1}{2} = 3",
        r"x_2 = \frac{5-1}{2} = 2",
        "Ответ: 2; 3",
        "",
    ]
    verify_solution(lines)
    started = time.monotonic()
    verify_solution(lines)
    assert time.monotonic() - started < 1.0


def test_adversarial_input_is_time_bounded() -> None:
    lines = [
        "x^{12} - 7x^{11} + 3x^5 - x + 1 = 0",
        "(x+1)^{40} = (x-1)^{40}",
        r"\frac{x^9+x^8+x^7}{x^5-x^3+x} = \sqrt{x^7+3}",
        "9^{9^{9}} = x",
        "x" * 600,
    ] * 8
    started = time.monotonic()
    result = verify_solution(lines)
    assert time.monotonic() - started < 3.5
    assert result.status in set(Status)


def test_result_is_picklable_and_runs_in_process_pool() -> None:
    lines = ["5x - 3 = 2x + 9", "3x = 12", "x = 4"]
    context = multiprocessing.get_context("forkserver")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as pool:
        result = pool.submit(verify_solution, lines).result(timeout=60)
    assert result.status is Status.CORRECT


def test_leading_constant_header_is_not_taken_as_task() -> None:
    result = verify_solution(
        [
            r"\sqrt{5}.",
            "x^3 - 11x + 48 = 0",
            "x^3 - 11x + 48 = (x + 3)(x^2 - 3x + 16)",
            r"x + 3 = 0 \Rightarrow x = -3",
        ]
    )
    assert result.status is Status.ERROR
    assert result.problem_kind is ProblemKind.EQUATION
    assert result.first_error_step == 2


def test_wrong_factorization_is_reported_as_factoring() -> None:
    result = verify_solution(
        [
            "x^3 - 11x + 48 = (x + 3)(x^2 - 3x + 16)",
            r"x + 3 = 0 \Rightarrow x = -3",
        ],
        "x^3 - 11x + 48 = 0",
    )
    assert result.status is Status.ERROR
    assert result.first_error_step == 0
    assert result.error_type is ErrorType.FACTORING


def test_correct_factorization_still_passes() -> None:
    result = verify_solution(
        ["x^3 + 7x + 48 = (x + 3)(x^2 - 3x + 16)", "x + 3 = 0", "x = -3"],
        "x^3 + 7x + 48 = 0",
    )
    assert result.error_type is None
