from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from yasno.clock import utcnow
from yasno.db.models import (
    ConsentStatus,
    Exam,
    Mistake,
    Notification,
    Quiz,
    Submission,
    TopicProgress,
    User,
)
from yasno.security import derive_key, sign_token, verify_token
from yasno.storage import Storage

PARENT_TOKEN_TTL_SECONDS = 7 * 24 * 3600


def _key(bot_token: str) -> bytes:
    return derive_key(bot_token, "parent-consent")


def parent_token(bot_token: str, user_id: int) -> str:
    return sign_token(_key(bot_token), user_id, PARENT_TOKEN_TTL_SECONDS)


def parent_token_subject(bot_token: str, token: str) -> int | None:
    return verify_token(_key(bot_token), token)


def grant(user: User) -> None:
    user.consent_status = ConsentStatus.GRANTED
    user.consented_at = utcnow()


def has_consent(user: User) -> bool:
    return user.consent_status is ConsentStatus.GRANTED


async def erase_user_data(session: AsyncSession, storage: Storage, user: User) -> int:
    await session.refresh(user, with_for_update=True)
    submissions = (
        (
            await session.execute(
                delete(Submission)
                .where(Submission.user_id == user.id)
                .returning(Submission.image_key)
            )
        )
        .scalars()
        .all()
    )
    await session.execute(delete(Mistake).where(Mistake.user_id == user.id))
    await session.execute(delete(TopicProgress).where(TopicProgress.user_id == user.id))
    await session.execute(delete(Quiz).where(Quiz.user_id == user.id))
    await session.execute(delete(Exam).where(Exam.user_id == user.id))
    await session.execute(delete(Notification).where(Notification.user_id == user.id))
    user.consent_status = ConsentStatus.REVOKED
    user.consented_at = None
    for key in submissions:
        if key:
            await storage.delete(key)
    return len(submissions)
