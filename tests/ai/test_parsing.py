import pytest
from pydantic import BaseModel

from yasno.ai.latex import latex_to_plain, normalize_latex, plain, similarity
from yasno.ai.parsing import JsonParseError, extract_json, parse_model
from yasno.ai.transcription import transcription_from_text


class Answer(BaseModel):
    text: str
    question: str


def test_extracts_json_from_fence_with_chatter() -> None:
    raw = 'Конечно!\n```json\n{"text": "a", "question": "b?",}\n```\nУдачи'
    assert extract_json(raw) == {"text": "a", "question": "b?"}


def test_extracts_json_embedded_in_text() -> None:
    assert extract_json('ответ: {"a": 1} готово') == {"a": 1}


def test_parse_model_rejects_wrong_shape() -> None:
    with pytest.raises(JsonParseError):
        parse_model(Answer, '{"text": "a"}')


def test_extract_json_fails_on_garbage() -> None:
    with pytest.raises(JsonParseError):
        extract_json("никакого json")


def test_latex_normalization() -> None:
    assert normalize_latex(r"$2x + 3 = 7$") == "2x+3=7"
    assert normalize_latex(r"\left( x \right)^{2} \leq 4") == "(x)^2<=4"
    assert latex_to_plain(r"\frac{x+1}{2} = \sqrt{9}") == "(x+1)/(2)=sqrt(9)"
    assert latex_to_plain("x^{2} - 4 = 0") == plain("x² − 4 = 0")
    assert similarity("2x=10", "2x=10") == 1.0


def test_transcription_is_renumbered_and_flagged() -> None:
    raw = """```json
    {"task": "null", "lines": [
      {"latex": "$2x + 3 = 7$", "confidence": "0.9"},
      {"latex": "", "text": ""},
      {"latex": "2x = \\\\square", "confidence": 3},
      {"latex": "", "text": "Ответ: 2", "is_math": false}
    ]}
    ```"""
    result = transcription_from_text(raw)
    assert result.task is None
    assert [line.index for line in result.lines] == [1, 2, 3]
    assert result.lines[0].latex == "2x + 3 = 7"
    assert result.lines[0].confidence == 0.9
    assert result.lines[1].illegible
    assert result.lines[1].confidence == 1.0
    assert not result.lines[2].is_math
    assert result.is_math
