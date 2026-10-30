import importlib
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.api.deps import get_session, get_settings_dep
from yasno.config import Settings
from yasno.math.errors import ERROR_TITLES, ErrorType
from yasno.storage import Storage


def _load_display() -> Callable[[str], object] | None:
    try:
        module = importlib.import_module("yasno.math.display")
    except ImportError:
        return None
    func: Any = getattr(module, "to_display", None)
    return func if callable(func) else None


_to_display = _load_display()


def display_text(latex: str, fallback: str = "") -> str:
    if not latex:
        return fallback
    if _to_display is None:
        return fallback or latex
    try:
        result = _to_display(latex)
    except Exception:
        return fallback or latex
    return result if isinstance(result, str) and result else fallback or latex


def parse_error_type(value: object) -> ErrorType | None:
    if not isinstance(value, str):
        return None
    try:
        return ErrorType(value)
    except ValueError:
        return None


def error_title(value: object) -> str | None:
    error_type = parse_error_type(value)
    if error_type is not None:
        return ERROR_TITLES[error_type]
    return ERROR_TITLES[ErrorType.OTHER] if isinstance(value, str) and value else None


def optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def decode_cursor(cursor: str | None) -> int | None:
    if cursor is None or cursor == "":
        return None
    if not cursor.isdigit() or len(cursor) > 19:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_cursor")
    return int(cursor)


def next_cursor(ids: list[int], limit: int) -> str | None:
    return str(ids[limit - 1]) if len(ids) > limit else None


PageLimit = Annotated[int, Query(ge=1, le=50)]


def get_storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


Session = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
AppStorage = Annotated[Storage, Depends(get_storage)]
