from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from yasno.api.webapp.auth import CurrentUser
from yasno.api.webapp.common import Session, display_text, optional_str, parse_error_type
from yasno.api.webapp.schemas import (
    ActiveQuizOut,
    AnswerIn,
    AnswerOut,
    ChoiceOut,
    QuizItemOut,
    QuizOut,
    QuizSummary,
)
from yasno.db.models import Quiz, QuizItem, QuizStatus, TopicProgress
from yasno.math.errors import ErrorType
from yasno.math.topics import topic_title
from yasno.services.progress import record_mistake, record_success

router = APIRouter(prefix="/quizzes")


def choice_text(choice: dict[str, Any]) -> str:
    for key in ("text", "display", "label"):
        value = optional_str(choice.get(key))
        if value is not None:
            return value
    latex = optional_str(choice.get("latex"))
    return display_text(latex) if latex is not None else ""


def choice_explanation(choice: dict[str, Any]) -> str | None:
    for key in ("explanation", "hint", "feedback"):
        value = optional_str(choice.get(key))
        if value is not None:
            return value
    return None


def _choice(item: QuizItem, index: int) -> dict[str, Any]:
    if 0 <= index < len(item.choices) and isinstance(item.choices[index], dict):
        return item.choices[index]
    return {}


def summarize(quiz: Quiz) -> QuizSummary:
    answered = [item for item in quiz.items if item.answered_index is not None]
    titles = list(dict.fromkeys(topic_title(item.topic_code) for item in quiz.items))
    return QuizSummary(
        id=quiz.id,
        reason=quiz.reason,
        status=quiz.status,
        created_at=quiz.created_at,
        total=len(quiz.items),
        answered=len(answered),
        correct=sum(1 for item in answered if item.answered_index == item.correct_index),
        topic_titles=titles,
    )


async def _gap_topics(session: Session, user_id: int) -> set[str]:
    rows = await session.execute(
        select(TopicProgress.topic_code).where(
            TopicProgress.user_id == user_id, TopicProgress.mistakes_total > 0
        )
    )
    return set(rows.scalars())


async def _load_quiz(session: Session, quiz_id: int, user_id: int) -> Quiz:
    result = await session.execute(
        select(Quiz)
        .where(Quiz.id == quiz_id, Quiz.user_id == user_id)
        .options(selectinload(Quiz.items))
        .execution_options(populate_existing=True)
    )
    quiz = result.scalar_one_or_none()
    if quiz is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="quiz_not_found")
    return quiz


@router.get("/active")
async def active_quiz(user: CurrentUser, session: Session) -> ActiveQuizOut:
    result = await session.execute(
        select(Quiz)
        .where(Quiz.user_id == user.id, Quiz.status == QuizStatus.ACTIVE)
        .options(selectinload(Quiz.items))
        .order_by(Quiz.id.desc())
        .limit(1)
    )
    quiz = result.scalar_one_or_none()
    if quiz is None or not quiz.items:
        return ActiveQuizOut(quiz=None)
    return ActiveQuizOut(quiz=summarize(quiz))


@router.get("/{quiz_id}")
async def get_quiz(quiz_id: int, user: CurrentUser, session: Session) -> QuizOut:
    quiz = await _load_quiz(session, quiz_id, user.id)
    gap_topics = await _gap_topics(session, user.id)
    items = [
        QuizItemOut(
            id=item.id,
            position=item.position,
            topic_code=item.topic_code,
            topic_title=topic_title(item.topic_code),
            prompt=item.prompt,
            choices=[
                ChoiceOut(index=index, text=choice_text(choice))
                for index, choice in enumerate(item.choices)
                if isinstance(choice, dict)
            ],
            from_gap_map=item.topic_code in gap_topics,
            answered_index=item.answered_index,
            correct_index=item.correct_index if item.answered_index is not None else None,
            is_correct=item.answered_index == item.correct_index
            if item.answered_index is not None
            else None,
        )
        for item in quiz.items
    ]
    return QuizOut(**summarize(quiz).model_dump(), items=items)


@router.post("/{quiz_id}/items/{item_id}/answer")
async def answer(
    quiz_id: int, item_id: int, body: AnswerIn, user: CurrentUser, session: Session
) -> AnswerOut:
    result = await session.execute(
        select(QuizItem)
        .join(Quiz, Quiz.id == QuizItem.quiz_id)
        .where(QuizItem.id == item_id, QuizItem.quiz_id == quiz_id, Quiz.user_id == user.id)
        .with_for_update(of=QuizItem)
        .execution_options(populate_existing=True)
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="item_not_found")
    already_answered = item.answered_index is not None
    if not already_answered:
        quiz = await _load_quiz(session, quiz_id, user.id)
        if quiz.status is not QuizStatus.ACTIVE:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="quiz_closed")
        if body.choice_index >= len(item.choices):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="invalid_choice")
        now = datetime.now(UTC)
        item.answered_index = body.choice_index
        item.answered_at = now
        if body.choice_index == item.correct_index:
            await record_success(session, user_id=user.id, topic_code=item.topic_code, now=now)
        else:
            chosen = _choice(item, body.choice_index)
            await record_mistake(
                session,
                user_id=user.id,
                topic_code=item.topic_code,
                error_type=parse_error_type(chosen.get("error_type")) or ErrorType.OTHER,
                now=now,
                quiz_item_id=item.id,
                detail={"quiz_id": quiz_id, "choice_index": body.choice_index},
            )
        await session.flush()
        if all(other.answered_index is not None for other in quiz.items):
            quiz.status = QuizStatus.COMPLETED
            quiz.completed_at = now
        await session.commit()
    quiz = await _load_quiz(session, quiz_id, user.id)
    summary = summarize(quiz)
    chosen_index = item.answered_index if item.answered_index is not None else body.choice_index
    return AnswerOut(
        item_id=item.id,
        chosen_index=chosen_index,
        correct_index=item.correct_index,
        is_correct=chosen_index == item.correct_index,
        explanation=choice_explanation(_choice(item, chosen_index)),
        already_answered=already_answered,
        quiz_status=quiz.status,
        answered=summary.answered,
        total=summary.total,
        correct=summary.correct,
    )
