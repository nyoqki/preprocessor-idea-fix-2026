import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.db.models import Role, SchoolClass, User

INVITE_ALPHABET = string.ascii_letters + string.digits
INVITE_LENGTH = 10


def new_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(INVITE_LENGTH))


def guess_grade(title: str) -> int | None:
    digits = "".join(ch if ch.isdigit() else " " for ch in title).split()
    for chunk in digits:
        value = int(chunk)
        if 5 <= value <= 11:
            return value
    return None


async def class_for_chat(session: AsyncSession, chat_id: int) -> SchoolClass | None:
    result = await session.execute(select(SchoolClass).where(SchoolClass.max_chat_id == chat_id))
    return result.scalar_one_or_none()


async def ensure_class_for_chat(
    session: AsyncSession, chat_id: int, title: str | None
) -> tuple[SchoolClass, bool]:
    existing = await class_for_chat(session, chat_id)
    if existing is not None:
        if title and existing.title != title:
            existing.title = title
        return existing, False
    clean_title = (title or "Класс").strip()[:200]
    school_class = SchoolClass(
        title=clean_title,
        grade=guess_grade(clean_title),
        max_chat_id=chat_id,
        invite_code=new_invite_code(),
    )
    session.add(school_class)
    await session.flush()
    return school_class, True


async def class_by_invite(session: AsyncSession, code: str) -> SchoolClass | None:
    result = await session.execute(select(SchoolClass).where(SchoolClass.invite_code == code))
    return result.scalar_one_or_none()


async def join_class(
    session: AsyncSession, user: User, school_class: SchoolClass, role: Role
) -> None:
    user.class_id = school_class.id
    user.role = role
    if role is Role.STUDENT and user.grade is None:
        user.grade = school_class.grade


async def class_size(session: AsyncSession, class_id: int) -> int:
    result = await session.execute(
        select(func.count()).select_from(User).where(User.class_id == class_id)
    )
    return int(result.scalar_one())


async def students_of(session: AsyncSession, class_id: int) -> list[User]:
    result = await session.execute(
        select(User).where(User.class_id == class_id, User.role == Role.STUDENT)
    )
    return list(result.scalars())
