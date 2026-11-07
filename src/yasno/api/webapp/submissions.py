from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import select

from yasno.api.webapp.auth import CurrentUser, sign_media_token, verify_media_token
from yasno.api.webapp.common import (
    AppSettings,
    AppStorage,
    PageLimit,
    ResourceId,
    Session,
    decode_cursor,
    display_text,
    error_title,
    next_cursor,
    optional_int,
    optional_str,
)
from yasno.api.webapp.schemas import (
    AnalysisOut,
    BBox,
    LineOut,
    SubmissionDetail,
    SubmissionOut,
    SubmissionPage,
)
from yasno.config import Settings
from yasno.db.models import Submission, SubmissionKind
from yasno.math.topics import topic_title
from yasno.media import sniff_image_type
from yasno.storage import InvalidKeyError, ObjectNotFoundError

router = APIRouter(prefix="/submissions")


def image_scope(submission_id: int) -> str:
    return f"submission-image:{submission_id}"


def _analysis(submission: Submission) -> dict[str, Any]:
    return submission.analysis if isinstance(submission.analysis, dict) else {}


def _bbox(value: object) -> BBox | None:
    if not isinstance(value, dict):
        return None
    try:
        return BBox.model_validate(value)
    except ValueError:
        return None


def _image_url(submission: Submission, settings: Settings) -> str | None:
    if submission.image_key is None:
        return None
    token = sign_media_token(image_scope(submission.id), settings.max_bot_token.get_secret_value())
    return f"/api/v1/submissions/{submission.id}/image?token={token}"


def to_out(submission: Submission, settings: Settings) -> SubmissionOut:
    analysis = _analysis(submission)
    error_type = optional_str(analysis.get("error_type"))
    return SubmissionOut(
        id=submission.id,
        created_at=submission.created_at,
        status=submission.status,
        verdict=optional_str(analysis.get("status")),
        topic_code=submission.topic_code,
        topic_title=topic_title(submission.topic_code) if submission.topic_code else None,
        error_type=error_type,
        error_title=error_title(error_type),
        first_error_step=optional_int(analysis.get("first_error_step")),
        image_url=_image_url(submission, settings),
    )


def _lines(submission: Submission, error_step: int | None) -> list[LineOut]:
    transcription = submission.transcription if isinstance(submission.transcription, dict) else {}
    raw_lines = transcription.get("lines")
    result: list[LineOut] = []
    for position, raw in enumerate(raw_lines if isinstance(raw_lines, list) else []):
        if not isinstance(raw, dict):
            continue
        index = optional_int(raw.get("index"))
        index = position if index is None else index
        latex = optional_str(raw.get("latex")) or ""
        text = optional_str(raw.get("text")) or ""
        confidence = raw.get("confidence")
        result.append(
            LineOut(
                index=index,
                latex=latex,
                display=display_text(latex, text),
                confidence=float(confidence) if isinstance(confidence, int | float) else 1.0,
                bbox=_bbox(raw.get("bbox")),
                is_error=error_step is not None and index == error_step,
            )
        )
    return result


async def _owned(session: Session, submission_id: int, user_id: int) -> Submission:
    submission = await session.get(Submission, submission_id)
    if submission is None or submission.user_id != user_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="submission_not_found")
    return submission


@router.get("")
async def list_submissions(
    user: CurrentUser,
    session: Session,
    settings: AppSettings,
    cursor: str | None = None,
    limit: PageLimit = 20,
) -> SubmissionPage:
    after = decode_cursor(cursor)
    stmt = (
        select(Submission)
        .where(Submission.user_id == user.id, Submission.kind != SubmissionKind.MATERIAL)
        .order_by(Submission.id.desc())
        .limit(limit + 1)
    )
    if after is not None:
        stmt = stmt.where(Submission.id < after)
    rows = list((await session.execute(stmt)).scalars())
    return SubmissionPage(
        items=[to_out(row, settings) for row in rows[:limit]],
        next_cursor=next_cursor([row.id for row in rows], limit),
    )


@router.get("/{submission_id}")
async def get_submission(
    submission_id: ResourceId, user: CurrentUser, session: Session, settings: AppSettings
) -> SubmissionDetail:
    submission = await _owned(session, submission_id, user.id)
    base = to_out(submission, settings)
    analysis = _analysis(submission)
    lines = _lines(submission, base.first_error_step)
    transcription = submission.transcription if isinstance(submission.transcription, dict) else {}
    error_line = next((line for line in lines if line.is_error), None)
    return SubmissionDetail(
        **base.model_dump(),
        task=optional_str(transcription.get("task")),
        lines=lines,
        analysis=AnalysisOut(
            status=base.verdict,
            first_error_step=base.first_error_step,
            error_type=base.error_type,
            error_title=base.error_title,
            hint=optional_str(analysis.get("hint")),
        )
        if analysis
        else None,
        error_bbox=error_line.bbox if error_line is not None else None,
        finished_at=submission.finished_at,
    )


@router.get("/{submission_id}/image")
async def get_submission_image(
    submission_id: ResourceId,
    session: Session,
    settings: AppSettings,
    storage: AppStorage,
    token: Annotated[str, Query(max_length=128)] = "",
) -> Response:
    if not verify_media_token(
        token, image_scope(submission_id), settings.max_bot_token.get_secret_value()
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="invalid_token")
    submission = await session.get(Submission, submission_id)
    if submission is None or submission.image_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="image_not_found")
    try:
        data = await storage.get(submission.image_key)
    except (ObjectNotFoundError, InvalidKeyError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="image_not_found") from exc
    return Response(
        content=data,
        media_type=sniff_image_type(data),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
