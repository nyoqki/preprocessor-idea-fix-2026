import re
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from yasno.api.webapp.auth import CurrentUser
from yasno.api.webapp.common import PageLimit, Session, decode_cursor, next_cursor
from yasno.api.webapp.schemas import MaterialOut, MaterialPage
from yasno.db.models import Material
from yasno.math.topics import topic_title

router = APIRouter(prefix="/materials")

SNIPPET_RADIUS = 90
_SPACES = re.compile(r"\s+")


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def make_snippet(content: str, query: str, radius: int = SNIPPET_RADIUS) -> str:
    text = _SPACES.sub(" ", content).strip()
    if not text:
        return ""
    position = text.casefold().find(query.casefold()) if query else -1
    if position < 0:
        return text if len(text) <= radius * 2 else text[: radius * 2].rstrip() + "…"
    start = max(0, position - radius)
    end = min(len(text), position + len(query) + radius)
    if start > 0:
        space = text.find(" ", start, position)
        start = space + 1 if space != -1 else start
    if end < len(text):
        space = text.rfind(" ", position + len(query), end)
        end = space if space != -1 else end
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


@router.get("")
async def search_materials(
    user: CurrentUser,
    session: Session,
    q: Annotated[str, Query(max_length=200)] = "",
    cursor: str | None = None,
    limit: PageLimit = 20,
) -> MaterialPage:
    if user.class_id is None:
        return MaterialPage(has_class=False, items=[], next_cursor=None)
    query = _SPACES.sub(" ", q).strip()
    after = decode_cursor(cursor)
    stmt = (
        select(Material)
        .where(Material.class_id == user.class_id)
        .order_by(Material.id.desc())
        .limit(limit + 1)
    )
    if query:
        pattern = f"%{escape_like(query)}%"
        stmt = stmt.where(
            or_(
                Material.title.ilike(pattern, escape="\\"),
                Material.content.ilike(pattern, escape="\\"),
            )
        )
    if after is not None:
        stmt = stmt.where(Material.id < after)
    rows = list((await session.execute(stmt)).scalars())
    return MaterialPage(
        has_class=True,
        items=[
            MaterialOut(
                id=row.id,
                title=row.title,
                snippet=make_snippet(row.content, query),
                topic_titles=[topic_title(code) for code in row.topic_codes],
                created_at=row.created_at,
            )
            for row in rows[:limit]
        ],
        next_cursor=next_cursor([row.id for row in rows], limit),
    )
