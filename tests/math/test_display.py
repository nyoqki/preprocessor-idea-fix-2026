import pytest

from yasno.math.display import to_display


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        ("x^{2} - 5x + 6 = 0", "x² − 5x + 6 = 0"),
        ("x^3", "x³"),
        (r"\frac{1}{2}", "½"),
        (r"\frac{x+1}{x-2}", "(x + 1)/(x − 2)"),
        (r"\frac{-b \pm \sqrt{D}}{2a}", "(−b ± √D)/(2a)"),
        (r"\sqrt{x+1} = 2", "√(x + 1) = 2"),
        (r"\sqrt{2}", "√2"),
        (r"\sqrt[3]{x}", "³√x"),
        (r"x \le 3", "x ≤ 3"),
        (r"x \geq -1", "x ≥ −1"),
        (r"x \neq 2", "x ≠ 2"),
        (r"x \in (-\infty; 3] \cup [5; +\infty)", "x ∈ (−∞; 3] ∪ [5; +∞)"),
        (r"\log_{2}(x) = 3", "log₂(x) = 3"),
        (r"2 \cdot 3", "2·3"),
        (r"x_{1} = 2; x_{2} = 3", "x₁ = 2; x₂ = 3"),
        (r"\left(x+1\right)^{2}", "(x + 1)²"),
        (r"2^{x+1}", "2ˣ⁺¹"),
        (r"\varnothing", "∅"),
        ("- 2 a b + b^{2}", "−2ab + b²"),
        (r"\text{Ответ: } x = 2", "Ответ: x = 2"),
        (r"\tan x", "tg x"),
        ("$x^{10}$", "x¹⁰"),
        (r"a^{\frac{1}{2}}", "a^½"),
    ],
)
def test_to_display(latex: str, expected: str) -> None:
    assert to_display(latex) == expected


def test_display_never_fails_on_broken_latex() -> None:
    for broken in [r"\frac{1}{", "x^{", r"\sqrt[3", "}{", "\\"]:
        assert isinstance(to_display(broken), str)
