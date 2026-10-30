import structlog

from yasno.bot import texts
from yasno.bot.common import callback_args, ensure_user, open_app_row, reply
from yasno.bot.context import BotContext
from yasno.bot.routing import Router, callback_prefix
from yasno.clock import utcnow
from yasno.db.models import Exam, Quiz, QuizItem, QuizReason, User
from yasno.math.topics import topic_title
from yasno.max import keyboard
from yasno.max.types import Update, UpdateType
from yasno.services import consent, quizzes

log = structlog.get_logger(__name__)

router = Router()

BUTTON_TEXT_LIMIT = 120


def question_text(quiz: Quiz, item: QuizItem) -> str:
    return texts.QUIZ_QUESTION.format(
        number=item.position + 1,
        total=len(quiz.items),
        topic=topic_title(item.topic_code),
        prompt=item.prompt,
    )


def question_rows(quiz: Quiz, item: QuizItem) -> list[list[keyboard.Button]]:
    rows = []
    for index, choice in enumerate(item.choices):
        label = str(choice.get("text") or choice.get("latex") or index + 1)[:BUTTON_TEXT_LIMIT]
        rows.append([keyboard.callback(label, f"quiz:a:{quiz.id}:{item.id}:{index}")])
    return rows


async def send_question(ctx: BotContext, user: User, quiz: Quiz) -> None:
    item = quizzes.next_item(quiz)
    if item is None:
        await send_result(ctx, user, quiz)
        return
    await reply(ctx, user.max_user_id, question_text(quiz, item), question_rows(quiz, item))


async def send_result(ctx: BotContext, user: User, quiz: Quiz) -> None:
    correct = sum(1 for item in quiz.items if item.answered_index == item.correct_index)
    template = texts.QUIZ_DONE_PERFECT if correct == len(quiz.items) else texts.QUIZ_DONE
    await reply(
        ctx,
        user.max_user_id,
        template.format(correct=correct, total=len(quiz.items)),
        [open_app_row(ctx, texts.BUTTON_OPEN_APP, "map")],
    )


async def _start(ctx: BotContext, user: User, args: list[str]) -> Quiz | None:
    async with ctx.sessions.begin() as session:
        match args:
            case ["exam", raw_id] if raw_id.isdigit():
                exam = await session.get(Exam, int(raw_id))
                if exam is None:
                    return None
                quiz = await quizzes.exam_quiz(session, user, exam)
            case ["review" | "topic" as kind, topic]:
                reason = QuizReason.REVIEW if kind == "review" else QuizReason.MANUAL
                try:
                    quiz = await quizzes.topic_quiz(session, user, topic, reason)
                except quizzes.QuizNotFoundError:
                    return None
            case _:
                return None
        return await quizzes.load_quiz(session, quiz.id, user.id)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("quiz"))
async def on_quiz_callback(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    callback_id = update.callback.callback_id
    args = callback_args(update)
    user = await ensure_user(ctx, update.callback.user)
    if args[:1] == ["later"]:
        await ctx.max.answer_callback(callback_id, text=texts.QUIZ_LATER)
        return
    if not consent.has_consent(user):
        await ctx.max.answer_callback(callback_id, notification=texts.CONSENT_REQUIRED)
        return
    if args[:1] == ["a"]:
        await _answer(ctx, user, callback_id, args[1:])
        return
    quiz = await _start(ctx, user, args)
    if quiz is None or not quiz.items:
        await ctx.max.answer_callback(callback_id, text=texts.QUIZ_UNAVAILABLE)
        return
    await ctx.max.answer_callback(
        callback_id, text=texts.QUIZ_STARTED.format(total=len(quiz.items))
    )
    await send_question(ctx, user, quiz)


async def _answer(ctx: BotContext, user: User, callback_id: str, args: list[str]) -> None:
    if len(args) != 3 or not all(part.isdigit() for part in args):
        await ctx.max.answer_callback(callback_id, notification=texts.QUIZ_UNAVAILABLE)
        return
    quiz_id, item_id, choice = (int(part) for part in args)
    try:
        async with ctx.sessions.begin() as session:
            result = await quizzes.answer_item(
                session,
                user_id=user.id,
                quiz_id=quiz_id,
                item_id=item_id,
                choice_index=choice,
                now=utcnow(),
            )
            quiz = await quizzes.load_quiz(session, quiz_id, user.id)
    except quizzes.QuizError as exc:
        log.info("quiz_answer_rejected", reason=type(exc).__name__)
        await ctx.max.answer_callback(callback_id, notification=texts.QUIZ_UNAVAILABLE)
        return
    if result.already_answered:
        await ctx.max.answer_callback(callback_id, notification=texts.QUIZ_ALREADY_ANSWERED)
        return
    item = result.item
    correct_text = str(quizzes.choice_at(item, item.correct_index).get("text") or "")
    feedback = (
        texts.QUIZ_RIGHT
        if result.is_correct
        else texts.QUIZ_WRONG.format(
            answer=correct_text, explanation=f"\n{result.explanation}" if result.explanation else ""
        )
    )
    await ctx.max.answer_callback(callback_id, text=f"{question_text(quiz, item)}\n\n{feedback}")
    await send_question(ctx, user, quiz)
