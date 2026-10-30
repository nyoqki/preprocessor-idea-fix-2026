from datetime import date

import pytest

from yasno.ai.exams import (
    detect_subject,
    exam_kind,
    looks_like_exam_announcement,
    resolve_exam_date,
)

FRIDAY = date(2026, 10, 30)


@pytest.mark.parametrize(
    "text",
    [
        "Завтра контрольная по алгебре",
        "к/р в пятницу",
        "КР по геометрии",
        "самостоялка на следующей неделе",
        "Проверочная работа 12.11",
        "в среду тест по алгебре",
        "Зачёт по теме логарифмы",
        "ВПР 5 ноября",
        "математический диктант во вторник",
    ],
)
def test_detects_announcements(text: str) -> None:
    assert looks_like_exam_announcement(text)


@pytest.mark.parametrize(
    "text",
    ["Мама испекла тесто", "Кто сделал домашку?", "встречаемся у школы", "пойдём в кино в пятницу"],
)
def test_ignores_regular_messages(text: str) -> None:
    assert not looks_like_exam_announcement(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("контрольная завтра", date(2026, 10, 31)),
        ("послезавтра тест", date(2026, 11, 1)),
        ("сегодня самостоятельная", FRIDAY),
        ("через 3 дня зачёт", date(2026, 11, 2)),
        ("через неделю кр", date(2026, 11, 6)),
        ("в понедельник кр", date(2026, 11, 2)),
        ("в пятницу кр", date(2026, 11, 6)),
        ("в эту пятницу кр", FRIDAY),
        ("на следующей неделе в четверг тест", date(2026, 11, 5)),
        ("во вт проверочная", date(2026, 11, 3)),
        ("КР 12.11", date(2026, 11, 12)),
        ("кр 01.09", date(2027, 9, 1)),
        ("кр 15.10.2026", None),
        ("ВПР 5 ноября", date(2026, 11, 5)),
        ("контрольная 20 октября", date(2027, 10, 20)),
        ("кр по теме x = 2.5", None),
        ("контрольная скоро", None),
    ],
)
def test_resolves_dates_never_in_past(text: str, expected: date | None) -> None:
    assert resolve_exam_date(text, FRIDAY) == expected


def test_kind_and_subject() -> None:
    assert exam_kind("самостоялка по алгебре") == "Самостоятельная работа"
    assert exam_kind("к/р") == "Контрольная работа"
    assert detect_subject("кр по геометрии") == "геометрия"
    assert detect_subject("тест по матеше") == "математика"
    assert detect_subject("тест") is None
