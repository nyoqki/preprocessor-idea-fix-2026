from dataclasses import dataclass

import structlog
from sqlalchemy import Text, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from yasno.ai.tutor import Tutor
from yasno.ai.types import ProviderError
from yasno.db.models import Material
from yasno.media import SUPPORTED_FOR_RECOGNITION, image_key, sniff_image_type
from yasno.storage import Storage

log = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MaterialResult:
    material_id: int
    title: str


async def recognize_text(tutor: Tutor, image: bytes, content_type: str) -> str:
    if tutor.ocr is not None:
        try:
            result = await tutor.ocr.recognize(image, content_type)
        except ProviderError as exc:
            log.warning("material_ocr_failed", error=str(exc))
        else:
            if result.text.strip():
                return result.text
    transcription = await tutor.transcribe(image, content_type)
    parts = [transcription.task or ""]
    parts.extend(line.text or line.latex for line in transcription.lines)
    return "\n".join(part for part in parts if part)


async def ingest_material(
    sessions: async_sessionmaker[AsyncSession],
    storage: Storage,
    tutor: Tutor,
    *,
    class_id: int,
    uploader_id: int | None,
    image: bytes,
) -> MaterialResult | None:
    content_type = sniff_image_type(image)
    if content_type not in SUPPORTED_FOR_RECOGNITION:
        return None
    try:
        text = await recognize_text(tutor, image, content_type)
    except ProviderError as exc:
        log.warning("material_recognition_failed", class_id=class_id, error=str(exc))
        return None
    if not text.strip():
        return None
    summary = await tutor.summarize_material(text)
    key = image_key("materials", class_id, content_type)
    await storage.put(key, image, content_type)
    async with sessions.begin() as session:
        material = Material(
            class_id=class_id,
            uploader_id=uploader_id,
            title=summary.title,
            image_key=key,
            content=text,
            topic_codes=summary.topic_codes,
        )
        session.add(material)
        await session.flush()
        material_id = material.id
    log.info("material_ingested", class_id=class_id, material_id=material_id, chars=len(text))
    return MaterialResult(material_id, summary.title)


async def relevant_materials(
    session: AsyncSession, class_id: int, query: str, limit: int = 3
) -> list[str]:
    document = func.to_tsvector("russian", Material.content)
    terms = func.to_tsquery(
        "russian", func.replace(cast(func.plainto_tsquery("russian", query), Text), "&", "|")
    )
    result = await session.execute(
        select(Material.title, Material.content)
        .where(Material.class_id == class_id, document.op("@@")(terms))
        .order_by(func.ts_rank(document, terms).desc())
        .limit(limit)
    )
    return [f"{title or 'Конспект'}\n{content[:1500]}" for title, content in result.all()]
