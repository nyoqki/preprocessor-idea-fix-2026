import json
from datetime import date

import pytest

from yasno.ai.fakes import DEFAULT_TRANSCRIPTION, FakeChat, FakeOcr, FakeVision
from yasno.ai.matching import attach_bboxes
from yasno.ai.registry import AiServices
from yasno.ai.resilience import AiUnavailableError
from yasno.ai.tutor import Tutor
from yasno.ai.types import BoundingBox, OcrLine, OcrResult, ProviderError, Role
from yasno.math.errors import ERROR_TITLES, ErrorType

LINES = DEFAULT_TRANSCRIPTION.lines
FRIDAY = date(2026, 10, 30)


def hint(text: str, question: str = "Что происходит со знаком при переносе?") -> str:
    return json.dumps({"text": text, "question": question}, ensure_ascii=False)


async def test_hint_happy_path_hides_expected_from_output_but_uses_it() -> None:
    chat = FakeChat([hint("Посмотри на строку 2: при переносе слагаемого меняется знак.")])
    result = await Tutor(chat).hint_for_error(
        "Реши уравнение 2x + 3 = 7", LINES, 2, ErrorType.SIGN, "2x = 7 - 3", 8
    )
    assert not result.safe_fallback
    assert result.question.endswith("?")
    system, user = chat.calls[0]
    assert system.role is Role.SYSTEM
    assert "8 класса" in system.content
    assert "2x = 7 - 3" in user.content
    assert ERROR_TITLES[ErrorType.SIGN] in user.content
    assert chat.schemas[0] is not None


async def test_hint_regenerates_on_leak_then_succeeds() -> None:
    chat = FakeChat(
        [
            hint("Правильно будет 2x = 7 - 3."),
            hint("Вспомни правило переноса слагаемых через знак равенства."),
        ]
    )
    result = await Tutor(chat).hint_for_error(None, LINES, 2, ErrorType.SIGN, "2x = 7 - 3", 8)
    assert result.text.startswith("Вспомни")
    assert len(chat.calls) == 2
    assert "раскрыла ответ" in chat.calls[1][0].content


async def test_hint_falls_back_to_template_after_two_regenerations() -> None:
    leaky = hint("Ответ: x = 2, проверь.")
    chat = FakeChat([leaky, leaky, leaky, hint("не дойдёт")])
    result = await Tutor(chat).hint_for_error(
        None, LINES, 2, ErrorType.SIGN, None, 9, forbidden=["x = 2"]
    )
    assert result.safe_fallback
    assert ERROR_TITLES[ErrorType.SIGN] in result.text
    assert "строку 2" in result.text
    assert result.question.endswith("?")
    assert len(chat.calls) == 3


async def test_hint_custom_leak_check() -> None:
    chat = FakeChat([hint("секрет"), hint("секрет"), hint("секрет")])
    result = await Tutor(chat).hint_for_error(
        None, LINES, 2, ErrorType.ARITHMETIC, None, 8, leak_check=lambda text: "секрет" in text
    )
    assert result.safe_fallback


async def test_short_forbidden_answer_only_matches_as_value() -> None:
    chat = FakeChat([hint("Посмотри на 2 строку: что стало со знаком?")])
    result = await Tutor(chat).hint_for_error(
        None, LINES, 2, ErrorType.SIGN, None, 8, forbidden=["2"]
    )
    assert not result.safe_fallback


async def test_hint_falls_back_when_provider_down() -> None:
    chat = FakeChat([AiUnavailableError("chat", [ProviderError("a", "down")])])
    result = await Tutor(chat).hint_for_error(None, LINES, 3, ErrorType.FRACTIONS, None, 8)
    assert result.safe_fallback
    assert "строку 3" in result.text


async def test_malformed_json_is_repaired_once() -> None:
    chat = FakeChat(["Конечно! Вот подсказка без json", hint("Посмотри на знак.")])
    result = await Tutor(chat).hint_for_error(None, LINES, 2, ErrorType.SIGN, None, 8)
    assert result.text == "Посмотри на знак."
    repair = chat.calls[1]
    assert repair[-2].role is Role.ASSISTANT
    assert "не удалось разобрать" in repair[-1].content


async def test_hint_accepts_fenced_json_and_adds_question_mark() -> None:
    chat = FakeChat([f"```json\n{hint('Проверь знак.', 'Что с ним стало')}\n```"])
    result = await Tutor(chat).hint_for_error(None, LINES, 2, ErrorType.SIGN, None, 8)
    assert result.question == "Что с ним стало?"


async def test_soft_review_rejects_assertive_wording() -> None:
    chat = FakeChat(
        [
            hint("Здесь ошибка в площади.", "Пересчитаешь?"),
            hint("Мне не до конца понятен второй шаг.", "Объяснишь, откуда он?"),
        ]
    )
    result = await Tutor(chat).soft_review("Найди площадь", LINES, 9)
    assert result.text.startswith("Мне не до конца")
    assert not result.safe_fallback


async def test_soft_review_template_on_failure() -> None:
    chat = FakeChat([ProviderError("a", "down")])
    result = await Tutor(chat).soft_review(None, LINES, 9)
    assert result.safe_fallback
    assert "ошибк" not in result.message.lower()


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ('{"code": "alg.linear_eq", "confidence": 0.9}', "alg.linear_eq"),
        ('{"code": "alg.made_up", "confidence": 0.9}', None),
        ('{"code": null, "confidence": 0.2}', None),
    ],
)
async def test_topic_is_constrained_to_taxonomy(reply: str, code: str | None) -> None:
    chat = FakeChat([reply])
    guess = await Tutor(chat).classify_topic("2x + 3 = 7", LINES)
    assert guess.code == code
    assert "alg.quadratic_eq" in chat.calls[0][0].content


async def test_exam_extraction_uses_deterministic_weekday() -> None:
    reply = {
        "is_exam": True,
        "subject": "Алгебра",
        "title": "Контрольная по квадратным уравнениям",
        "date": "2026-10-01",
        "topic_codes": ["alg.quadratic_eq", "nonsense"],
    }
    chat = FakeChat([json.dumps(reply, ensure_ascii=False)])
    exam = await Tutor(chat).extract_exam("В пятницу кр по квадратным уравнениям!", FRIDAY)
    assert exam is not None
    assert exam.date == date(2026, 11, 6)
    assert exam.subject == "алгебра"
    assert exam.topic_codes == ["alg.quadratic_eq"]
    assert exam.title == "Контрольная по квадратным уравнениям"
    assert "пятница" in chat.calls[0][0].content


async def test_exam_uses_llm_date_only_when_in_future() -> None:
    chat = FakeChat(['{"is_exam": true, "date": "2026-11-20", "title": "Тест"}'])
    exam = await Tutor(chat).extract_exam("тест после каникул", FRIDAY)
    assert exam is not None
    assert exam.date == date(2026, 11, 20)
    chat = FakeChat(['{"is_exam": true, "date": "2026-10-20", "title": "Тест"}'])
    exam = await Tutor(chat).extract_exam("тест после каникул", FRIDAY)
    assert exam is not None
    assert exam.date is None


async def test_exam_prefilter_skips_llm() -> None:
    chat = FakeChat()
    assert await Tutor(chat).extract_exam("кто идёт в кино?", FRIDAY) is None
    assert chat.calls == []


async def test_exam_llm_can_reject_and_failure_degrades() -> None:
    chat = FakeChat(['{"is_exam": false}'])
    assert await Tutor(chat).extract_exam("тест-драйв новой машины", FRIDAY) is None
    chat = FakeChat([ProviderError("a", "down")])
    exam = await Tutor(chat).extract_exam("Завтра самостоялка по геометрии", FRIDAY)
    assert exam is not None
    assert exam.title == "Самостоятельная работа"
    assert exam.subject == "геометрия"
    assert exam.date == date(2026, 10, 31)


async def test_answer_question_includes_materials_and_degrades() -> None:
    chat = FakeChat(["Дискриминант — это ..."])
    answer = await Tutor(chat).answer_question("Что такое дискриминант?", ["D = b^2 - 4ac"], 8)
    assert answer.startswith("Дискриминант")
    assert any("D = b^2 - 4ac" in m.content for m in chat.calls[0])
    assert chat.calls[0][-1].content == "Что такое дискриминант?"
    chat = FakeChat([ProviderError("a", "down")])
    answer = await Tutor(chat).answer_question("?", [], 8)
    assert "попробуй" in answer.lower()


async def test_summarize_material_filters_topics() -> None:
    chat = FakeChat(['{"title": "Теорема Виета", "topic_codes": ["alg.quadratic_eq", "x"]}'])
    summary = await Tutor(chat).summarize_material("Теорема Виета\nx1 + x2 = -b/a")
    assert summary.title == "Теорема Виета"
    assert summary.topic_codes == ["alg.quadratic_eq"]
    chat = FakeChat([ProviderError("a", "down")])
    summary = await Tutor(chat).summarize_material("Теорема Виета\nx1 + x2 = -b/a")
    assert summary.title == "Теорема Виета"


async def test_transcribe_attaches_ocr_bboxes() -> None:
    tutor = Tutor(FakeChat(), FakeVision(), FakeOcr())
    result = await tutor.transcribe(b"img", "image/jpeg")
    assert all(line.bbox is not None for line in result.lines)
    assert result.lines[0].bbox is not None
    assert result.lines[-1].bbox is not None
    assert result.lines[0].bbox.y < result.lines[-1].bbox.y


async def test_transcribe_survives_ocr_failure() -> None:
    tutor = Tutor(FakeChat(), FakeVision(), FakeOcr(ProviderError("ocr", "down")))
    result = await tutor.transcribe(b"img", "image/jpeg")
    assert len(result.lines) == 4
    assert all(line.bbox is None for line in result.lines)


async def test_transcribe_raises_when_vision_unavailable() -> None:
    tutor = Tutor(FakeChat(), FakeVision(ProviderError("v", "down")), FakeOcr())
    with pytest.raises(ProviderError):
        await tutor.transcribe(b"img", "image/jpeg")
    with pytest.raises(AiUnavailableError):
        await Tutor(FakeChat()).transcribe(b"img", "image/jpeg")


def test_attach_bboxes_skips_noise_and_keeps_order() -> None:
    def box(y: float) -> BoundingBox:
        return BoundingBox(x=0, y=y, width=0.5, height=0.05)

    ocr = OcrResult(
        lines=[
            OcrLine(text="Решение:", bbox=box(0.0)),
            OcrLine(text="2х+3=7", bbox=box(0.2)),
            OcrLine(text="2x = 7+3", bbox=box(0.4)),
            OcrLine(text="x=5", bbox=box(0.8)),
        ]
    )
    lines = attach_bboxes(LINES, ocr)
    assert [line.bbox.y if line.bbox else None for line in lines] == [0.2, 0.4, None, 0.8]


async def test_from_services_and_fake_dev_replies() -> None:
    services = AiServices(vision=FakeVision(), chat=FakeChat(), ocr=FakeOcr(), embedder=None)
    tutor = Tutor.from_services(services)
    guess = await tutor.classify_topic("2x + 3 = 7", LINES)
    assert guess.code == "alg.linear_eq"
    hint_result = await tutor.hint_for_error(None, LINES, 2, ErrorType.SIGN, None, 8)
    assert not hint_result.safe_fallback
