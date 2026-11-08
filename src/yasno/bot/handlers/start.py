from yasno.bot import memory, texts
from yasno.bot.common import callback_args, ensure_user, reply
from yasno.bot.context import BotContext
from yasno.bot.links import start_link
from yasno.bot.routing import Router, all_of, callback_prefix, command, in_dialog
from yasno.db.models import ConsentStatus, Role, User
from yasno.max import keyboard
from yasno.max.types import Update, UpdateType
from yasno.services import classes, consent
from yasno.services.access import is_chat_admin
from yasno.users import get_by_max_id, mark_dialog_unavailable

router = Router()

GRADES = (8, 9, 10, 11)


def grade_rows() -> list[list[keyboard.Button]]:
    return [[keyboard.callback(str(g), f"grade:{g}") for g in GRADES]]


def consent_rows() -> list[list[keyboard.Button]]:
    return [
        [
            keyboard.callback(texts.BUTTON_YES_14, "consent:adult"),
            keyboard.callback(texts.BUTTON_NO_14, "consent:minor"),
        ]
    ]


def parent_consent_rows() -> list[list[keyboard.Button]]:
    return [[keyboard.callback(texts.BUTTON_CORRECT_AGE, "age:change")]]


def age_correction_rows() -> list[list[keyboard.Button]]:
    return [
        [keyboard.callback(texts.BUTTON_CONFIRM_14, "age:adult")],
        [keyboard.callback(texts.BUTTON_NO_14, "consent:minor")],
    ]


async def continue_onboarding(ctx: BotContext, user: User) -> None:
    if user.requires_parent_consent and not consent.has_consent(user):
        async with ctx.sessions.begin() as session:
            fresh = await session.get(User, user.id, with_for_update=True)
            assert fresh is not None
            if consent.has_consent(fresh):
                return
            fresh.consent_status = ConsentStatus.PENDING
        await reply(ctx, fresh.max_user_id, _parent_consent_text(ctx, fresh), parent_consent_rows())
        return
    if user.role is Role.TEACHER:
        if not consent.has_consent(user):
            await reply(
                ctx,
                user.max_user_id,
                texts.TEACHER_CONSENT,
                [[keyboard.callback("Согласен", "consent:adult")]],
            )
        return
    if user.grade is None:
        await reply(ctx, user.max_user_id, texts.ASK_GRADE, grade_rows())
        return
    if not consent.has_consent(user):
        await reply(ctx, user.max_user_id, texts.CONSENT_REQUEST, consent_rows())


async def _join(ctx: BotContext, user: User, code: str, role: Role) -> User | None:
    if role is Role.TEACHER:
        async with ctx.sessions() as session:
            school_class = await classes.class_by_invite(session, code)
        if school_class is None:
            return None
        if not await is_chat_admin(ctx.max, school_class.max_chat_id, user.max_user_id):
            await reply(ctx, user.max_user_id, texts.TEACHER_NOT_VERIFIED)
            return user
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id)
        school_class = await classes.class_by_invite(session, code)
        if fresh is None or school_class is None:
            return None
        await classes.join_class(session, fresh, school_class, role)
        title = school_class.title
    template = texts.JOINED_AS_TEACHER if role is Role.TEACHER else texts.JOINED_CLASS
    await reply(ctx, user.max_user_id, template.format(title=title))
    return fresh


def _parent_consent_text(ctx: BotContext, user: User) -> str:
    token = consent.parent_token(ctx.settings.max_bot_token.get_secret_value(), user.id)
    link = start_link(ctx.bot_username, f"parent_{token}")
    return texts.CONSENT_PARENT.format(link=link)


async def _parent(ctx: BotContext, user: User, token: str) -> None:
    child_id = consent.parent_token_subject(ctx.settings.max_bot_token.get_secret_value(), token)
    if child_id is None:
        await reply(ctx, user.max_user_id, texts.CONSENT_PARENT_INVALID)
        return
    async with ctx.sessions() as session:
        child = await session.get(User, child_id)
    if child is not None and child.max_user_id == user.max_user_id:
        await reply(ctx, user.max_user_id, texts.CONSENT_PARENT_SELF)
        return
    if child is None or child.consent_status is not ConsentStatus.PENDING:
        await reply(ctx, user.max_user_id, texts.CONSENT_PARENT_INVALID)
        return
    rows = [[keyboard.callback(texts.BUTTON_PARENT_AGREE, f"parent:{token}")]]
    await reply(ctx, user.max_user_id, texts.CONSENT_PARENT_CONFIRM, rows)


@router.on(UpdateType.BOT_STARTED)
async def on_bot_started(update: Update, ctx: BotContext) -> None:
    actor = update.actor
    if actor is None:
        return
    user = await ensure_user(ctx, actor)
    payload = (update.payload or "").strip()
    if payload.startswith("parent_"):
        await _parent(ctx, user, payload.removeprefix("parent_"))
        return
    await reply(ctx, actor.user_id, texts.GREETING.format(name=actor.first_name or "друг"))
    if payload.startswith("join_"):
        user = await _join(ctx, user, payload.removeprefix("join_"), Role.STUDENT) or user
    elif payload.startswith("teach_"):
        joined = await _join(ctx, user, payload.removeprefix("teach_"), Role.TEACHER)
        if joined is None:
            await reply(ctx, actor.user_id, texts.INVITE_INVALID)
        else:
            await continue_onboarding(ctx, joined)
        return
    await continue_onboarding(ctx, user)


@router.on(UpdateType.BOT_STOPPED)
async def on_bot_stopped(update: Update, ctx: BotContext) -> None:
    if update.actor_id is None:
        return
    async with ctx.sessions.begin() as session:
        await mark_dialog_unavailable(session, update.actor_id)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, command("start", "help")))
async def on_start_command(update: Update, ctx: BotContext) -> None:
    actor = update.actor
    if actor is None:
        return
    user = await ensure_user(ctx, actor)
    await reply(ctx, actor.user_id, texts.GREETING.format(name=actor.first_name or "друг"))
    await continue_onboarding(ctx, user)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, command("age")))
async def on_age_command(update: Update, ctx: BotContext) -> None:
    if update.actor is None:
        return
    await ensure_user(ctx, update.actor)
    await reply(
        ctx,
        update.actor.user_id,
        texts.AGE_CORRECTION + texts.CONSENT_REQUEST,
        age_correction_rows(),
    )


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("age"))
async def on_age_correction(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    args = callback_args(update)
    if args == ["change"]:
        await ctx.max.answer_callback(
            update.callback.callback_id,
            text=texts.AGE_CORRECTION + texts.CONSENT_REQUEST,
            attachments=[keyboard.inline_keyboard(age_correction_rows())],
        )
        return
    if args != ["adult"]:
        return
    user = await ensure_user(ctx, update.callback.user)
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id, with_for_update=True)
        assert fresh is not None
        fresh.requires_parent_consent = False
        consent.grant(fresh)
    text = texts.TEACHER_CONSENT_GRANTED if fresh.role is Role.TEACHER else texts.CONSENT_GRANTED
    await ctx.max.answer_callback(update.callback.callback_id, text=text, attachments=[])
    await continue_onboarding(ctx, fresh)


@router.on(UpdateType.MESSAGE_CREATED, all_of(in_dialog, command("delete")))
async def on_delete_command(update: Update, ctx: BotContext) -> None:
    if update.actor is None:
        return
    rows = [
        [
            keyboard.callback(texts.BUTTON_DELETE, "data:delete"),
            keyboard.callback(texts.BUTTON_CANCEL, "data:keep"),
        ]
    ]
    await reply(ctx, update.actor.user_id, texts.DELETE_CONFIRM, rows)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("data"))
async def on_delete_choice(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    actor = update.callback.user
    if callback_args(update)[:1] != ["delete"]:
        await ctx.max.answer_callback(update.callback.callback_id, notification="Ок")
        return
    async with ctx.sessions.begin() as session:
        user = await get_by_max_id(session, actor.user_id)
        if user is not None:
            await consent.erase_user_data(session, ctx.storage, user)
    if user is not None:
        await memory.forget(ctx, user)
        await ctx.redis.delete(f"fix:{user.id}", f"followup:{user.id}")
    await ctx.max.answer_callback(update.callback.callback_id, text=texts.DATA_DELETED)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("grade"))
async def on_grade(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    args = callback_args(update)
    if not args or not args[0].isdigit() or int(args[0]) not in GRADES:
        return
    grade = int(args[0])
    user = await ensure_user(ctx, update.callback.user)
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id)
        assert fresh is not None
        fresh.grade = grade
    await ctx.max.answer_callback(
        update.callback.callback_id, text=texts.GRADE_SAVED.format(grade=grade)
    )
    await continue_onboarding(ctx, fresh)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("consent"))
async def on_consent(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    args = callback_args(update)
    if args not in (["adult"], ["minor"]):
        return
    user = await ensure_user(ctx, update.callback.user)
    async with ctx.sessions.begin() as session:
        fresh = await session.get(User, user.id, with_for_update=True)
        assert fresh is not None
        if args == ["minor"]:
            fresh.requires_parent_consent = True
            fresh.consent_status = ConsentStatus.PENDING
            fresh.consented_at = None
        elif not fresh.requires_parent_consent:
            consent.grant(fresh)
        elif not consent.has_consent(fresh):
            fresh.consent_status = ConsentStatus.PENDING
    if fresh.requires_parent_consent and not consent.has_consent(fresh):
        text = _parent_consent_text(ctx, fresh)
        attachments = [keyboard.inline_keyboard(parent_consent_rows())]
    else:
        text = (
            texts.TEACHER_CONSENT_GRANTED if fresh.role is Role.TEACHER else texts.CONSENT_GRANTED
        )
        attachments = []
    await ctx.max.answer_callback(update.callback.callback_id, text=text, attachments=attachments)


@router.on(UpdateType.MESSAGE_CALLBACK, callback_prefix("parent"))
async def on_parent_agree(update: Update, ctx: BotContext) -> None:
    assert update.callback is not None
    token = ":".join(callback_args(update))
    child_id = consent.parent_token_subject(ctx.settings.max_bot_token.get_secret_value(), token)
    if child_id is None:
        await ctx.max.answer_callback(
            update.callback.callback_id, text=texts.CONSENT_PARENT_INVALID
        )
        return
    async with ctx.sessions.begin() as session:
        child = await session.get(User, child_id, with_for_update=True)
        if child is None:
            await ctx.max.answer_callback(
                update.callback.callback_id, text=texts.CONSENT_PARENT_INVALID
            )
            return
        if child.max_user_id == update.callback.user.user_id:
            await ctx.max.answer_callback(
                update.callback.callback_id, text=texts.CONSENT_PARENT_SELF
            )
            return
        if child.consent_status is not ConsentStatus.PENDING:
            await ctx.max.answer_callback(
                update.callback.callback_id, text=texts.CONSENT_PARENT_INVALID
            )
            return
        consent.grant(child)
        child_max_id = child.max_user_id
    await ctx.max.answer_callback(update.callback.callback_id, text=texts.CONSENT_PARENT_DONE)
    await reply(ctx, child_max_id, texts.CONSENT_CHILD_NOTIFIED)
