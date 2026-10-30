import pytest

from yasno.math.leak import reveals_answer
from yasno.math.verify import verify_solution

QUADRATIC = ["x^2 - 5x + 6 = 0", "D = 25 + 24 = 49", r"x_1 = \frac{5+7}{2} = 6"]
INEQUALITY = ["-2x + 4 > 0", "-2x > -4", "x > 2"]
EXPRESSION = ["(a-b)^2 - a^2", "= a^2 - b^2 - a^2"]


@pytest.mark.parametrize(
    "hint",
    [
        "Правильный ответ: x = 2 и x = 3.",
        "Корни уравнения 2 и 3",
        "Должно получиться x₁ = 3",
        "Дискриминант равен 1, а не 49.",
        "$x_{1} = 3$, $x_{2} = 2$",
        "Ответ: 2; 3",
    ],
)
def test_quadratic_leaks(hint: str) -> None:
    verification = verify_solution(QUADRATIC)
    assert reveals_answer(hint, verification, context=QUADRATIC)


@pytest.mark.parametrize(
    "hint",
    [
        "Вспомни формулу дискриминанта: D = b² − 4ac. Какой знак стоит перед 4ac?",
        "Проверь, как ты подставил коэффициенты a, b и c.",
        "Посмотри внимательно на знак перед слагаемым 24.",
    ],
)
def test_quadratic_safe_hints(hint: str) -> None:
    verification = verify_solution(QUADRATIC)
    assert not reveals_answer(hint, verification, context=QUADRATIC)


def test_inequality_leaks() -> None:
    verification = verify_solution(INEQUALITY)
    assert reveals_answer("Должно быть x < 2", verification, context=INEQUALITY)
    assert reveals_answer("Ответ: x ∈ (−∞; 2)", verification, context=INEQUALITY)
    assert not reveals_answer(
        "Что происходит со знаком неравенства при делении на отрицательное число?",
        verification,
        context=INEQUALITY,
    )


def test_expression_leaks() -> None:
    verification = verify_solution(EXPRESSION)
    assert reveals_answer("Должно получиться b² − 2ab", verification, context=EXPRESSION)
    assert reveals_answer("Верно: a^2 - 2ab + b^2 - a^2", verification, context=EXPRESSION)
    assert not reveals_answer(
        "Вспомни формулу квадрата разности: (a − b)² ≠ a² − b².",
        verification,
        context=EXPRESSION,
    )


def test_empty_hint_is_safe() -> None:
    assert not reveals_answer("   ", verify_solution(QUADRATIC))
