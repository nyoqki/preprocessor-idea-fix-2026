from enum import StrEnum


class ErrorType(StrEnum):
    SIGN = "sign"
    ARITHMETIC = "arithmetic"
    DISTRIBUTION = "distribution"
    FRACTIONS = "fractions"
    POWERS = "powers"
    ROOTS = "roots"
    LOST_ROOT = "lost_root"
    EXTRANEOUS_ROOT = "extraneous_root"
    DOMAIN = "domain"
    DIVISION_BY_VARIABLE = "division_by_variable"
    INEQUALITY_FLIP = "inequality_flip"
    FORMULA = "formula"
    OTHER = "other"


ERROR_TITLES: dict[ErrorType, str] = {
    ErrorType.SIGN: "Ошибка в знаке",
    ErrorType.ARITHMETIC: "Ошибка в вычислении",
    ErrorType.DISTRIBUTION: "Раскрытие скобок",
    ErrorType.FRACTIONS: "Действия с дробями",
    ErrorType.POWERS: "Свойства степеней",
    ErrorType.ROOTS: "Свойства корней",
    ErrorType.LOST_ROOT: "Потерян корень",
    ErrorType.EXTRANEOUS_ROOT: "Лишний корень",
    ErrorType.DOMAIN: "Область допустимых значений",
    ErrorType.DIVISION_BY_VARIABLE: "Деление на выражение с переменной",
    ErrorType.INEQUALITY_FLIP: "Знак неравенства при умножении на отрицательное",
    ErrorType.FORMULA: "Неверная формула",
    ErrorType.OTHER: "Другая ошибка",
}
