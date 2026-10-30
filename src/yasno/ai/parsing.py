import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError

_FENCE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


class JsonParseError(ValueError):
    pass


def _candidates(text: str) -> list[str]:
    stripped = text.strip()
    found = [stripped]
    found.extend(match.strip() for match in _FENCE.findall(text))
    for opener, closer in (("{", "}"), ("[", "]")):
        start = stripped.find(opener)
        end = stripped.rfind(closer)
        if start != -1 and end > start:
            found.append(stripped[start : end + 1])
    return found


def extract_json(text: str) -> Any:
    for candidate in _candidates(text):
        for variant in (candidate, _TRAILING_COMMA.sub(r"\1", candidate)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError:
                continue
    raise JsonParseError("no valid JSON found in model output")


def parse_model[M: BaseModel](model: type[M], text: str) -> M:
    data = extract_json(text)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise JsonParseError(
            f"JSON does not match {model.__name__}: {exc.error_count()} errors"
        ) from exc
