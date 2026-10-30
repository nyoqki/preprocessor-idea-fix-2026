from dataclasses import dataclass
from enum import StrEnum


class Subject(StrEnum):
    ALGEBRA = "algebra"
    GEOMETRY = "geometry"


@dataclass(frozen=True, slots=True)
class Topic:
    code: str
    title: str
    subject: Subject
    grades: tuple[int, ...]
    verifiable: bool


TOPICS: tuple[Topic, ...] = (
    Topic("arith.fractions", "Действия с дробями", Subject.ALGEBRA, (5, 6, 7, 8, 9), True),
    Topic("arith.powers", "Степени и их свойства", Subject.ALGEBRA, (7, 8, 9), True),
    Topic("alg.roots", "Квадратные корни", Subject.ALGEBRA, (8, 9), True),
    Topic("alg.expressions", "Преобразование выражений", Subject.ALGEBRA, (7, 8, 9), True),
    Topic("alg.factoring", "Разложение на множители", Subject.ALGEBRA, (7, 8, 9), True),
    Topic("alg.rational_expr", "Рациональные дроби", Subject.ALGEBRA, (8, 9), True),
    Topic("alg.linear_eq", "Линейные уравнения", Subject.ALGEBRA, (7, 8, 9), True),
    Topic("alg.quadratic_eq", "Квадратные уравнения", Subject.ALGEBRA, (8, 9), True),
    Topic("alg.rational_eq", "Дробно-рациональные уравнения", Subject.ALGEBRA, (8, 9), True),
    Topic("alg.irrational_eq", "Иррациональные уравнения", Subject.ALGEBRA, (10, 11), True),
    Topic("alg.systems", "Системы уравнений", Subject.ALGEBRA, (7, 8, 9), True),
    Topic("alg.linear_ineq", "Линейные неравенства", Subject.ALGEBRA, (8, 9), True),
    Topic("alg.quadratic_ineq", "Квадратные неравенства", Subject.ALGEBRA, (8, 9, 10), True),
    Topic("alg.progressions", "Прогрессии", Subject.ALGEBRA, (9,), True),
    Topic("alg.functions", "Функции и графики", Subject.ALGEBRA, (8, 9, 10), False),
    Topic("alg.exponential", "Показательные уравнения", Subject.ALGEBRA, (10, 11), True),
    Topic("alg.logarithms", "Логарифмы", Subject.ALGEBRA, (10, 11), True),
    Topic("trig.expressions", "Тригонометрические выражения", Subject.ALGEBRA, (10, 11), True),
    Topic("trig.equations", "Тригонометрические уравнения", Subject.ALGEBRA, (10, 11), True),
    Topic("calc.derivative", "Производная", Subject.ALGEBRA, (10, 11), True),
    Topic("prob.basic", "Вероятность и статистика", Subject.ALGEBRA, (8, 9, 10, 11), False),
    Topic("word.problems", "Текстовые задачи", Subject.ALGEBRA, (8, 9, 10, 11), False),
    Topic("geom.planimetry", "Планиметрия", Subject.GEOMETRY, (8, 9), False),
    Topic("geom.stereometry", "Стереометрия", Subject.GEOMETRY, (10, 11), False),
)

TOPICS_BY_CODE: dict[str, Topic] = {topic.code: topic for topic in TOPICS}


def get_topic(code: str) -> Topic | None:
    return TOPICS_BY_CODE.get(code)


def topic_title(code: str) -> str:
    topic = TOPICS_BY_CODE.get(code)
    return topic.title if topic is not None else code
