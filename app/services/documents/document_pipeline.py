from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.domain.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.infrastructure.db.models import (
    Category,
    Document,
    DocumentCategory,
    DocumentChunk,
    DocumentEntity,
    DocumentTag,
    Entity,
    ProcessingJob,
    Tag,
)
from app.schemas.documents import DocumentExtractResponse, DocumentUpdateRequest, SummarySource
from app.schemas.extract import RefineSummaryMode
from app.services.documents.db_refs import (
    document_type_id_by_code,
    entity_type_id_by_code,
    language_id_by_code,
    prediction_source_id,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.llm.categorizer import categorize_text
from app.services.llm.entity_extractor import extract_entities
from app.services.llm.summarizer import refine_summary, summarize_text
from app.services.llm.tagger import tag_text
from app.services.llm.translator import detect_language, translate_text
from app.services.processing.jobs import JobStatus, JobType, processing_job


def _map_lang_for_db(detected: str) -> str:
    if detected in ("ru", "de", "en"):
        return detected
    return "en"


async def get_document_by_source_url(session: AsyncSession, url: str) -> Document | None:
    norm = normalize_source_url(url)
    q = await session.execute(select(Document).where(Document.source_url == norm))
    return q.scalar_one_or_none()


def document_to_extract_response(doc: Document, *, from_cache: bool) -> DocumentExtractResponse:
    return DocumentExtractResponse(
        title=doc.title or None,
        author=None,
        date=None,
        url=doc.source_url,
        text=doc.original_content,
        length=len(doc.original_content or ""),
        method="cached" if from_cache else "live",
        quality="unknown" if from_cache else "ok",
        needs_review=False,
        images=[],
        main_image=None,
        document_id=doc.id,
        from_cache=from_cache,
        version=doc.version,
    )


async def create_document_after_extract(
    session: AsyncSession,
    *,
    norm_url: str,
    extract_payload: dict,
    created_by_id: uuid.UUID | None,
    document_type_code: str = "article",
) -> Document:
    text = extract_payload["text"]
    lang_code = _map_lang_for_db(await asyncio.to_thread(detect_language, text))
    ol_id = await language_id_by_code(session, lang_code)
    dt_id = await document_type_id_by_code(session, document_type_code)
    title = (extract_payload.get("title") or "").strip() or "Без названия"

    doc = Document(
        title=title[:512],
        original_content=text,
        original_language_id=ol_id,
        document_type_id=dt_id,
        source_url=norm_url,
        created_by_id=created_by_id,
        original_summary_stale=True,
        translated_summary_stale=True,
    )
    session.add(doc)
    await session.flush()
    return doc


async def record_completed_extract_job(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    duration_ms: int,
    started_by_id: uuid.UUID | None,
) -> None:
    job = ProcessingJob(
        document_id=document_id,
        job_type=JobType.EXTRACT,
        status=JobStatus.COMPLETED,
        model_name=None,
        provider=None,
        started_by_id=started_by_id,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        duration_ms=duration_ms,
    )
    session.add(job)


async def _manual_ps_id(session: AsyncSession) -> uuid.UUID:
    return await prediction_source_id(session, "manual")


async def _llm_ps_id(session: AsyncSession) -> uuid.UUID:
    return await prediction_source_id(session, "llm")


async def delete_auto_document_tags(session: AsyncSession, document_id: uuid.UUID) -> None:
    manual_id = await _manual_ps_id(session)
    await session.execute(
        delete(DocumentTag).where(
            DocumentTag.document_id == document_id,
            or_(
                DocumentTag.prediction_source_id.is_(None),
                DocumentTag.prediction_source_id != manual_id,
            ),
        )
    )


async def delete_auto_document_entities(session: AsyncSession, document_id: uuid.UUID) -> None:
    manual_id = await _manual_ps_id(session)
    await session.execute(
        delete(DocumentEntity).where(
            DocumentEntity.document_id == document_id,
            or_(
                DocumentEntity.prediction_source_id.is_(None),
                DocumentEntity.prediction_source_id != manual_id,
            ),
        )
    )


async def delete_auto_document_categories(session: AsyncSession, document_id: uuid.UUID) -> None:
    manual_id = await _manual_ps_id(session)
    await session.execute(
        delete(DocumentCategory).where(
            DocumentCategory.document_id == document_id,
            or_(
                DocumentCategory.prediction_source_id.is_(None),
                DocumentCategory.prediction_source_id != manual_id,
            ),
        )
    )


async def delete_all_document_chunks(session: AsyncSession, document_id: uuid.UUID) -> None:
    await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))


async def invalidate_auto_derivatives(session: AsyncSession, document_id: uuid.UUID) -> None:
    await delete_auto_document_tags(session, document_id)
    await delete_auto_document_entities(session, document_id)
    await delete_auto_document_categories(session, document_id)
    await delete_all_document_chunks(session, document_id)


async def get_document_for_update(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    q = await session.execute(select(Document).where(Document.id == document_id).with_for_update())
    return q.scalar_one_or_none()


async def acquire_edit_lock(session: AsyncSession, *, document_id: uuid.UUID, user_id: uuid.UUID) -> Document:
    doc = await get_document_for_update(session, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    now = datetime.now(UTC)
    if (
        doc.locked_by_id
        and doc.locked_by_id != user_id
        and doc.lock_expires_at
        and doc.lock_expires_at > now
    ):
        raise ConflictError("Документ заблокирован другим пользователем")
    ttl = settings.document_lock_expire_minutes
    doc.locked_by_id = user_id
    doc.locked_at = now
    doc.lock_expires_at = now + timedelta(minutes=ttl)
    return doc


async def save_document_after_edit(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    user_id: uuid.UUID,
    body: DocumentUpdateRequest,
) -> Document:
    doc = await get_document_for_update(session, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    now = datetime.now(UTC)
    if doc.locked_by_id != user_id:
        raise ForbiddenError("Документ не заблокирован вами")
    if doc.lock_expires_at is None or doc.lock_expires_at < now:
        raise ConflictError("Срок блокировки истёк или блокировка не установлена")

    if body.original_content is not None and body.original_content != doc.original_content:
        doc.original_summary_stale = True
    if body.translated_content is not None and body.translated_content != doc.translated_content:
        doc.translated_summary_stale = True

    if body.title is not None:
        doc.title = body.title.strip()[:512] or doc.title
    if body.original_content is not None:
        doc.original_content = body.original_content
    if body.translated_content is not None:
        doc.translated_content = body.translated_content

    doc.version = (doc.version or 1) + 1
    doc.locked_by_id = None
    doc.locked_at = None
    doc.lock_expires_at = None
    doc.updated_at = now

    await invalidate_auto_derivatives(session, document_id)
    return doc


async def _get_or_create_tag(session: AsyncSession, name: str, language_id: uuid.UUID) -> uuid.UUID:
    q = await session.execute(
        select(Tag.id).where(Tag.name == name, Tag.language_id == language_id).limit(1),
    )
    found = q.scalar_one_or_none()
    if found:
        return found
    tag = Tag(name=name[:128], language_id=language_id)
    session.add(tag)
    await session.flush()
    return tag.id


async def _get_or_create_entity(
    session: AsyncSession,
    name: str,
    entity_type_id: uuid.UUID,
    language_id: uuid.UUID,
) -> uuid.UUID:
    q = await session.execute(
        select(Entity.id).where(
            Entity.name == name,
            Entity.entity_type_id == entity_type_id,
            Entity.language_id == language_id,
        ),
    )
    found = q.scalar_one_or_none()
    if found:
        return found
    ent = Entity(
        name=name[:255],
        entity_type_id=entity_type_id,
        language_id=language_id,
    )
    session.add(ent)
    await session.flush()
    return ent.id


async def persist_document_translation(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    translated_text: str,
    target_lang: str,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.TRANSLATE,
        model_name=settings.model_translation,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.TRANSLATION,
    ):
        tl_id = await language_id_by_code(session, target_lang)
        doc.translated_content = translated_text
        doc.translated_language_id = tl_id
        doc.translated_summary_stale = True
    return doc


async def run_translate_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    target_lang: str,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    text = await translate_text(doc.original_content, target_lang=target_lang, stream=False)
    if not isinstance(text, str):
        raise ValidationError("Ожидалась строка перевода")
    return await persist_document_translation(
        session,
        document_id=document_id,
        translated_text=text,
        target_lang=target_lang,
        started_by_id=started_by_id,
    )


async def run_tag_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    max_tags: int,
    use_translation: bool,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    if use_translation:
        src = doc.translated_content or ""
        lang_id = doc.translated_language_id or doc.original_language_id
    else:
        src = doc.original_content
        lang_id = doc.original_language_id
    if not src.strip():
        raise ValidationError("Нет текста для тегирования")

    llm_ps = await _llm_ps_id(session)

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.TAG,
        model_name=settings.model_tagging,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.TAGGING,
    ):
        await delete_auto_document_tags(session, document_id)
        tags_payload = await tag_text(src, max_tags=max_tags)
        for tag_name in tags_payload.get("tags", []):
            tid = await _get_or_create_tag(session, tag_name, lang_id)
            session.add(
                DocumentTag(
                    document_id=document_id,
                    tag_id=tid,
                    prediction_source_id=llm_ps,
                ),
            )
    return doc


async def run_entity_extract_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    src = doc.original_content
    if not src.strip():
        raise ValidationError("Пустой исходный текст")

    lang_id = doc.original_language_id
    llm_ps = await _llm_ps_id(session)
    et_mil = await entity_type_id_by_code(session, "military_equipment")
    et_man = await entity_type_id_by_code(session, "manufacturer")
    et_con = await entity_type_id_by_code(session, "contract")

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.ENTITY_EXTRACT,
        model_name=settings.model_entity_extraction,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.ENTITY_EXTRACTION,
    ):
        await delete_auto_document_entities(session, document_id)
        raw = await extract_entities(src)
        for name in dict.fromkeys(raw.get("military_equipment", [])):
            eid = await _get_or_create_entity(session, name, et_mil, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
        for name in dict.fromkeys(raw.get("manufacturers", [])):
            eid = await _get_or_create_entity(session, name, et_man, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
        for name in dict.fromkeys(raw.get("contracts", [])):
            eid = await _get_or_create_entity(session, name, et_con, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
    return doc


async def run_categorize_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    src = doc.original_content
    if not src.strip():
        raise ValidationError("Пустой исходный текст")

    q = await session.execute(
        select(Category.code, Category.name, Category.name_ru).where(Category.is_active.is_(True)),
    )
    pairs = []
    for code, name, name_ru in q.all():
        label = f"{name_ru} — {name}" if name_ru else name
        pairs.append((code, label))
    llm_ps = await _llm_ps_id(session)

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.CATEGORIZE,
        model_name=settings.model_categorization,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.CATEGORIZATION,
    ):
        await delete_auto_document_categories(session, document_id)
        items = await categorize_text(src, pairs)
        for it in items:
            code = it["code"]
            cid = await session.scalar(select(Category.id).where(Category.code == code))
            if cid is None:
                continue
            conf = Decimal(str(it.get("confidence", 0.5)))
            session.add(
                DocumentCategory(
                    document_id=document_id,
                    category_id=cid,
                    confidence=conf,
                    prediction_source_id=llm_ps,
                ),
            )
    return doc


async def persist_document_refined_summary(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    refined_annotation: str,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.SUMMARY_REFINE,
        model_name=settings.model_summary_refine,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.SUMMARY_REFINE,
    ):
        # Summarizer/refiner prompts produce Russian; store in translated_summary only.
        doc.translated_summary = refined_annotation
        doc.translated_summary_stale = False
    return doc


async def persist_document_summary(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    annotation: str,
    started_by_id: uuid.UUID | None,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    async with processing_job(
        session,
        document_id=document_id,
        job_type=JobType.SUMMARY,
        model_name=settings.model_summary,
        provider=None,
        started_by_id=started_by_id,
        llm_task_for_provider=LLMTask.SUMMARY,
    ):
        # Summarizer prompts produce Russian; store in translated_summary only.
        doc.translated_summary = annotation
        doc.translated_summary_stale = False
    return doc


async def run_summary_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    started_by_id: uuid.UUID | None,
) -> tuple[Document, str]:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    if source == SummarySource.original:
        text = doc.original_content
    else:
        text = doc.translated_content or ""
    if not text.strip():
        raise ValidationError("Нет текста для аннотации")

    ann = await summarize_text(text, stream=False)
    if not isinstance(ann, str):
        raise ValidationError("Некорректный ответ суммаризатора")
    doc = await persist_document_summary(
        session,
        document_id=document_id,
        source=source,
        annotation=ann,
        started_by_id=started_by_id,
    )
    return doc, ann


async def run_refine_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    user_instruction: str,
    mode: RefineSummaryMode,
    started_by_id: uuid.UUID | None,
) -> tuple[Document, str]:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    if source == SummarySource.original:
        article = doc.original_content
    else:
        article = doc.translated_content or ""
    summary = doc.translated_summary or doc.original_summary or ""
    if not article.strip():
        raise ValidationError("Нет текста статьи")
    if not summary.strip():
        raise ValidationError("Нет аннотации для уточнения — сначала сгенерируйте summary")

    refined = await refine_summary(
        article_text=article,
        summary=summary,
        user_instruction=user_instruction,
        mode=mode,
        stream=False,
    )
    if not isinstance(refined, str):
        raise ValidationError("Некорректный ответ уточнения аннотации")
    doc = await persist_document_refined_summary(
        session,
        document_id=document_id,
        source=source,
        refined_annotation=refined,
        started_by_id=started_by_id,
    )
    return doc, refined
