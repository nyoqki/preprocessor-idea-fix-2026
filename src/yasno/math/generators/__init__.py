import random
from dataclasses import dataclass

from yasno.math.errors import ErrorType
from yasno.math.generators import algebra, arithmetic, calculus, equations, inequalities
from yasno.math.generators.base import CHOICES, Draft, Recipe, Rejected, Value
from yasno.math.limits import MathTimeout

MAX_ATTEMPTS = 40


@dataclass(frozen=True, slots=True)
class Choice:
    latex: str
    correct: bool
    error_type: ErrorType | None = None


@dataclass(frozen=True, slots=True)
class GeneratedProblem:
    topic_code: str
    instruction: str
    prompt_latex: str
    choices: tuple[Choice, ...]
    difficulty: int

    @property
    def correct_index(self) -> int:
        return next(index for index, choice in enumerate(self.choices) if choice.correct)


_RECIPES: dict[str, Recipe] = {
    "arith.fractions": arithmetic.fractions,
    "arith.powers": arithmetic.powers,
    "alg.roots": arithmetic.roots,
    "alg.expressions": algebra.expressions,
    "alg.factoring": algebra.factoring,
    "alg.progressions": algebra.progressions,
    "alg.linear_eq": equations.linear,
    "alg.quadratic_eq": equations.quadratic,
    "alg.rational_eq": equations.rational,
    "alg.systems": equations.systems,
    "alg.exponential": equations.exponential,
    "alg.logarithms": equations.logarithms,
    "alg.linear_ineq": inequalities.linear,
    "alg.quadratic_ineq": inequalities.quadratic,
    "calc.derivative": calculus.derivative,
}


def supported_topics() -> frozenset[str]:
    return frozenset(_RECIPES)


def _distractors(
    draft: Draft, rng: random.Random, focus: ErrorType | None
) -> list[tuple[Value, ErrorType]]:
    candidates = list(draft.distractors)
    rng.shuffle(candidates)
    if focus is not None:
        candidates.sort(key=lambda item: item[1] is not focus)
    chosen: list[tuple[Value, ErrorType]] = []
    seen: list[Value] = [draft.correct]
    for value, error in candidates:
        if not value.is_valid() or not value.round_trips():
            continue
        if any(value.same_as(other) for other in seen):
            continue
        if any(value.latex() == other.latex() for other in seen):
            continue
        chosen.append((value, error))
        seen.append(value)
        if len(chosen) == CHOICES - 1:
            break
    return chosen


def _assemble(
    topic_code: str,
    draft: Draft,
    rng: random.Random,
    difficulty: int,
    focus: ErrorType | None,
) -> GeneratedProblem:
    if not (draft.correct.is_valid() and draft.correct.round_trips()):
        raise Rejected
    distractors = _distractors(draft, rng, focus)
    if len(distractors) < CHOICES - 1:
        raise Rejected
    choices = [Choice(draft.correct.latex(), True)]
    choices += [Choice(value.latex(), False, error) for value, error in distractors]
    rng.shuffle(choices)
    return GeneratedProblem(
        topic_code=topic_code,
        instruction=draft.instruction,
        prompt_latex=draft.prompt,
        choices=tuple(choices),
        difficulty=difficulty,
    )


def generate(
    topic_code: str,
    rng: random.Random,
    *,
    difficulty: int = 1,
    focus: ErrorType | None = None,
) -> GeneratedProblem:
    recipe = _RECIPES.get(topic_code)
    if recipe is None:
        raise ValueError(f"unsupported topic: {topic_code}")
    level = min(max(difficulty, 1), 3)
    for _ in range(MAX_ATTEMPTS):
        try:
            return _assemble(topic_code, recipe(rng, level), rng, level, focus)
        except (Rejected, MathTimeout, ArithmeticError, ValueError):
            continue
    raise RuntimeError(f"could not generate a problem for {topic_code}")
