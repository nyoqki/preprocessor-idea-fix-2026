from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Identity,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yasno.db.base import Base, TimestampMixin


def pg_enum[E: StrEnum](enum: type[E], name: str) -> Enum:
    return Enum(enum, name=name, values_callable=lambda e: [m.value for m in e])


class Role(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"


class ConsentStatus(StrEnum):
    NONE = "none"
    PENDING = "pending"
    GRANTED = "granted"
    REVOKED = "revoked"


class SubmissionKind(StrEnum):
    HOMEWORK = "homework"
    MATERIAL = "material"
    ANSWER = "answer"


class SubmissionStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_CONFIRMATION = "needs_confirmation"
    DONE = "done"
    FAILED = "failed"


class ExamSource(StrEnum):
    STUDENT = "student"
    CHAT = "chat"
    TEACHER = "teacher"


class QuizReason(StrEnum):
    EXAM = "exam"
    REVIEW = "review"
    MANUAL = "manual"


class QuizStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class SchoolClass(TimestampMixin, Base):
    __tablename__ = "classes"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    max_chat_id: Mapped[int | None] = mapped_column(unique=True)
    invite_code: Mapped[str] = mapped_column(String(32), unique=True)
    bot_can_read_chat: Mapped[bool] = mapped_column(server_default=text("false"))

    members: Mapped[list["User"]] = relationship(back_populates="school_class")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    max_user_id: Mapped[int] = mapped_column(unique=True)
    first_name: Mapped[str] = mapped_column(String(200), server_default="")
    last_name: Mapped[str | None] = mapped_column(String(200))
    username: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(
        pg_enum(Role, "user_role"), server_default=Role.STUDENT.value
    )
    class_id: Mapped[int | None] = mapped_column(
        ForeignKey("classes.id", ondelete="SET NULL"), index=True
    )
    grade: Mapped[int | None] = mapped_column(SmallInteger)
    consent_status: Mapped[ConsentStatus] = mapped_column(
        pg_enum(ConsentStatus, "consent_status"), server_default=ConsentStatus.NONE.value
    )
    consented_at: Mapped[datetime | None]
    dialog_available: Mapped[bool] = mapped_column(server_default=text("true"))
    last_seen_at: Mapped[datetime | None]

    school_class: Mapped[SchoolClass | None] = relationship(back_populates="members")


class Submission(TimestampMixin, Base):
    __tablename__ = "submissions"
    __table_args__ = (Index("ix_submissions_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[SubmissionKind] = mapped_column(pg_enum(SubmissionKind, "submission_kind"))
    status: Mapped[SubmissionStatus] = mapped_column(
        pg_enum(SubmissionStatus, "submission_status"),
        server_default=SubmissionStatus.QUEUED.value,
    )
    image_key: Mapped[str | None] = mapped_column(String(300))
    image_sha256: Mapped[str | None] = mapped_column(String(64))
    source_mid: Mapped[str | None] = mapped_column(String(100))
    transcription: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    topic_code: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None]


class Mistake(TimestampMixin, Base):
    __tablename__ = "mistakes"
    __table_args__ = (Index("ix_mistakes_user_topic", "user_id", "topic_code"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL")
    )
    quiz_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("quiz_items.id", ondelete="SET NULL")
    )
    topic_code: Mapped[str] = mapped_column(String(32))
    error_type: Mapped[str] = mapped_column(String(64))
    step_index: Mapped[int | None] = mapped_column(SmallInteger)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None]


class TopicProgress(Base):
    __tablename__ = "topic_progress"
    __table_args__ = (Index("ix_topic_progress_due", "next_review_at"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    topic_code: Mapped[str] = mapped_column(String(32), primary_key=True)
    mistakes_total: Mapped[int] = mapped_column(server_default=text("0"))
    correct_total: Mapped[int] = mapped_column(server_default=text("0"))
    box: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_mistake_at: Mapped[datetime | None]
    last_practice_at: Mapped[datetime | None]
    next_review_at: Mapped[datetime | None]


class Exam(TimestampMixin, Base):
    __tablename__ = "exams"
    __table_args__ = (
        CheckConstraint("class_id IS NOT NULL OR user_id IS NOT NULL", name="owner"),
        Index("ix_exams_scheduled_on", "scheduled_on"),
    )

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    subject: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    topic_codes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=text("'{}'"))
    scheduled_on: Mapped[date]
    source: Mapped[ExamSource] = mapped_column(pg_enum(ExamSource, "exam_source"))
    source_mid: Mapped[str | None] = mapped_column(String(100))
    raw_text: Mapped[str | None] = mapped_column(Text)


class Quiz(TimestampMixin, Base):
    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"))
    reason: Mapped[QuizReason] = mapped_column(pg_enum(QuizReason, "quiz_reason"))
    status: Mapped[QuizStatus] = mapped_column(
        pg_enum(QuizStatus, "quiz_status"), server_default=QuizStatus.ACTIVE.value
    )
    completed_at: Mapped[datetime | None]

    items: Mapped[list["QuizItem"]] = relationship(
        back_populates="quiz", order_by="QuizItem.position", cascade="all, delete-orphan"
    )


class QuizItem(Base):
    __tablename__ = "quiz_items"
    __table_args__ = (UniqueConstraint("quiz_id", "position"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(SmallInteger)
    topic_code: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    correct_index: Mapped[int] = mapped_column(SmallInteger)
    answered_index: Mapped[int | None] = mapped_column(SmallInteger)
    answered_at: Mapped[datetime | None]

    quiz: Mapped[Quiz] = relationship(back_populates="items")


class Material(TimestampMixin, Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("classes.id", ondelete="CASCADE"), index=True)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    submission_id: Mapped[int | None] = mapped_column(
        ForeignKey("submissions.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, server_default="")
    topic_codes: Mapped[list[str]] = mapped_column(ARRAY(String(32)), server_default=text("'{}'"))


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "kind", "ref"),)

    id: Mapped[int] = mapped_column(Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(64))
    ref: Mapped[str] = mapped_column(String(128))
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
