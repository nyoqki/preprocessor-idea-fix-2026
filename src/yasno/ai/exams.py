import re
from datetime import date, timedelta

_EXAM_KINDS: tuple[tuple[str, str], ...] = (
    (r"контрольн\w*|к/р|кр", "Контрольная работа"),
    (r"самостоятельн\w*|самостоялк\w*|самостойк\w*|с/р|ср(?=\s+по\b)", "Самостоятельная работа"),
    (r"проверочн\w*|п/р", "Проверочная работа"),
    (r"тест(?:ы|а|е|у|ом|ов|овая|овую|овой|ирование\w*)?", "Тест"),
    (r"зач[её]т(?:а|е|у|ом|ы|ов|ная|ную|ной)?", "Зачёт"),
    (r"впр", "ВПР"),
    (r"диктант\w*|матдиктант\w*", "Диктант"),
    (r"срез\w*", "Срез"),
    (r"пробник\w*|пробн\w+\s+(?:огэ|егэ)", "Пробный экзамен"),
)

EXAM_PATTERN = re.compile(
    r"(?<![\w/])(?:" + "|".join(pattern for pattern, _ in _EXAM_KINDS) + r")(?![\w/])",
    re.IGNORECASE,
)
_KIND_PATTERNS = tuple(
    (re.compile(r"(?<![\w/])(?:" + pattern + r")(?![\w/])", re.IGNORECASE), title)
    for pattern, title in _EXAM_KINDS
)

_SUBJECTS: tuple[tuple[str, str], ...] = (
    (r"алгебр", "алгебра"),
    (r"геометр", "геометрия"),
    (r"матем|матеш|матан", "математика"),
    (r"физик", "физика"),
    (r"хими", "химия"),
    (r"информатик", "информатика"),
    (r"русск", "русский язык"),
    (r"литератур", "литература"),
    (r"англ", "английский язык"),
    (r"биолог", "биология"),
    (r"истори", "история"),
    (r"обществ", "обществознание"),
    (r"географ", "география"),
)

_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}
_MONTH_WORD = re.compile(
    r"(?<!\d)(\d{1,2})\s+(январ[яе]|феврал[яе]|марта?|апрел[яе]|ма[яе]|июн[яе]|июл[яе]|"
    r"августа?|сентябр[яе]|октябр[яе]|ноябр[яе]|декабр[яе])",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(r"(?<![\d./])(\d{1,2})[./](\d{2})(?:[./](\d{4}|\d{2}))?(?![./]?\d)")

_WEEKDAYS: tuple[tuple[str, int], ...] = (
    (r"понедельник\w*|пн", 0),
    (r"вторник\w*|вт", 1),
    (r"сред[ауы]|ср", 2),
    (r"четверг\w*|чт", 3),
    (r"пятниц[ауы]|пт", 4),
    (r"суббот[ауы]|сб", 5),
    (r"воскресень[ея]|вс", 6),
)
_WEEKDAY = re.compile(
    r"(?<!\w)(?:(?:в\s+|на\s+)?(?P<next>следующ\w+|ближайш\w+|эт\w+)\s+)?(?:(?:в|во|на)\s+)?"
    r"(?P<day>понедельник\w*|вторник\w*|сред[ауы]|четверг\w*|пятниц[ауы]|суббот[ауы]|"
    r"воскресень[ея])(?!\w)"
    r"|(?<!\w)(?:в|во|на)\s+(?P<short>пн|вт|ср|чт|пт|сб|вс)(?!\w)",
    re.IGNORECASE,
)
_NEXT_WEEK = re.compile(r"следующ\w+\s+недел|через\s+неделю\s+в", re.IGNORECASE)
_IN_DAYS = re.compile(
    r"через\s+(\d+|один|одну|два|две|три|четыре|пять|шесть)\s+(дн\w*|день|недел\w*)",
    re.IGNORECASE,
)
_NUMBERS = {"один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6}

WEEKDAY_NAMES = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def looks_like_exam_announcement(text: str) -> bool:
    return bool(EXAM_PATTERN.search(text))


def exam_kind(text: str) -> str:
    for pattern, title in _KIND_PATTERNS:
        if pattern.search(text):
            return title
    return "Проверочная работа"


def detect_subject(text: str) -> str | None:
    lowered = text.lower()
    for stem, subject in _SUBJECTS:
        if re.search(r"(?<!\w)" + stem, lowered):
            return subject
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _future(day: int, month: int, today: date, year: int | None = None) -> date | None:
    if year is not None:
        found = _safe_date(year, month, day)
        return found if found is not None and found >= today else None
    found = _safe_date(today.year, month, day)
    if found is not None and found < today:
        found = _safe_date(today.year + 1, month, day)
    return found


def _explicit_date(text: str, today: date) -> date | None:
    for match in _MONTH_WORD.finditer(text):
        word = match.group(2).lower()
        month = next(m for stem, m in _MONTHS.items() if word.startswith(stem))
        found = _future(int(match.group(1)), month, today)
        if found is not None:
            return found
    for match in _NUMERIC_DATE.finditer(text):
        raw_year = match.group(3)
        year = None
        if raw_year:
            year = int(raw_year) + (2000 if len(raw_year) == 2 else 0)
        found = _future(int(match.group(1)), int(match.group(2)), today, year)
        if found is not None:
            return found
    return None


def _relative_date(text: str, today: date) -> date | None:
    lowered = text.lower()
    if re.search(r"(?<!\w)послезавтра(?!\w)", lowered):
        return today + timedelta(days=2)
    if re.search(r"(?<!\w)завтра(?!\w)", lowered):
        return today + timedelta(days=1)
    if re.search(r"(?<!\w)сегодня(?!\w)", lowered):
        return today
    match = _IN_DAYS.search(lowered)
    if match:
        raw = match.group(1)
        amount = int(raw) if raw.isdigit() else _NUMBERS[raw]
        unit = 7 if match.group(2).startswith("недел") else 1
        return today + timedelta(days=amount * unit)
    if re.search(r"через\s+неделю(?!\s+в)", lowered):
        return today + timedelta(days=7)
    return None


def _weekday_index(word: str) -> int:
    lowered = word.lower()
    for pattern, index in _WEEKDAYS:
        if re.fullmatch(pattern, lowered):
            return index
    raise ValueError(word)


def _weekday_date(text: str, today: date) -> date | None:
    match = _WEEKDAY.search(text)
    if match is None:
        return None
    weekday = _weekday_index(match.group("day") or match.group("short"))
    modifier = (match.group("next") or "").lower()
    if modifier.startswith("следующ") or _NEXT_WEEK.search(text):
        next_monday = today + timedelta(days=7 - today.weekday())
        return next_monday + timedelta(days=weekday)
    delta = (weekday - today.weekday()) % 7
    if delta == 0 and not modifier.startswith("эт"):
        delta = 7
    return today + timedelta(days=delta)


def resolve_exam_date(text: str, today: date) -> date | None:
    return _explicit_date(text, today) or _relative_date(text, today) or _weekday_date(text, today)
