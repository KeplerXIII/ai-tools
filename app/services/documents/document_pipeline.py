from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import NoResultFound, ProgrammingError
from sqlalchemy.orm import aliased
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
    DocumentStatus,
    DocumentStatusAssignment,
    DocumentTag,
    Entity,
    ProcessingJob,
    Tag,
)
from app.schemas.documents import (
    DocumentCategorizeItem,
    DocumentEntityItem,
    DocumentExtractResponse,
    DocumentMetadataUpdateRequest,
    DocumentStatusItem,
    DocumentTagItem,
    DocumentUpdateRequest,
    SummarySource,
)
from app.schemas.extract import ImageInfo
from app.schemas.extract import RefineSummaryMode
from app.services.documents.db_refs import (
    document_type_id_by_code,
    entity_type_id_by_code,
    language_id_by_code,
    prediction_source_id,
)
from app.services.documents.document_embedding import (
    EmbeddingStage,
    embed_document_stages_if_stale,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.llm.categorizer import categorize_text
from app.services.llm.entity_extractor import extract_entities
from app.services.llm.summarizer import refine_summary, summarize_text
from app.services.llm.tagger import tag_text
from app.services.llm.translator import detect_language, translate_text
from app.services.processing.jobs import JobStatus, JobType, processing_job

logger = logging.getLogger(__name__)

NOT_FOUND_ENTITY_NAME = "не обнаружено"
FALLBACK_CATEGORY_CODE = "other_domain"


def _published_at_from_extract_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None
    s = str(date_str).strip()
    if not s:
        return None
    try:
        normalized = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _map_lang_for_db(detected: str) -> str:
    if detected in ("ru", "de", "en"):
        return detected
    return "en"


async def _attach_default_new_unprocessed_statuses(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    assigned_by_id: uuid.UUID | None,
) -> None:
    try:
        rows = (
            await session.execute(
                select(DocumentStatus.code, DocumentStatus.id).where(
                    DocumentStatus.code.in_(("new", "unprocessed"))
                )
            )
        ).all()
    except ProgrammingError as exc:
        if "document_statuses" in str(exc).lower():
            raise ValidationError(
                "Справочник статусов документов не инициализирован. Примените миграции и сиды БД."
            ) from None
        raise
    by_code = {code: sid for code, sid in rows}
    missing = [c for c in ("new", "unprocessed") if c not in by_code]
    if missing:
        raise ValidationError(
            f"Справочник статусов документов неполон: отсутствуют коды {', '.join(missing)}"
        )
    await session.execute(
        insert(DocumentStatusAssignment)
        .values(
            [
                {
                    "document_id": document_id,
                    "status_id": by_code["new"],
                    "assigned_by_id": assigned_by_id,
                },
                {
                    "document_id": document_id,
                    "status_id": by_code["unprocessed"],
                    "assigned_by_id": assigned_by_id,
                },
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[
                DocumentStatusAssignment.document_id,
                DocumentStatusAssignment.status_id,
            ]
        )
    )


async def _status_ids_by_code(
    session: AsyncSession,
    *,
    required_codes: tuple[str, ...],
) -> dict[str, uuid.UUID]:
    rows = (
        await session.execute(
            select(DocumentStatus.code, DocumentStatus.id).where(DocumentStatus.code.in_(required_codes)),
        )
    ).all()
    by_code = {code: sid for code, sid in rows}
    missing = [c for c in required_codes if c not in by_code]
    if missing:
        raise ValidationError(
            f"Справочник статусов документов неполон: отсутствуют коды {', '.join(missing)}"
        )
    return by_code


async def _has_document_tags_for_language(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    language_id: uuid.UUID,
) -> bool:
    return bool(
        await session.scalar(
            select(DocumentTag.document_id)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(
                DocumentTag.document_id == document_id,
                Tag.language_id == language_id,
            )
            .limit(1)
        )
    )


async def _is_document_fully_populated(session: AsyncSession, *, doc: Document) -> bool:
    has_translation = bool((doc.translated_content or "").strip()) and doc.translated_language_id is not None
    if not has_translation:
        return False
    translated_language_id = doc.translated_language_id
    assert translated_language_id is not None

    has_original_tags = await _has_document_tags_for_language(
        session,
        document_id=doc.id,
        language_id=doc.original_language_id,
    )
    has_translated_tags = await _has_document_tags_for_language(
        session,
        document_id=doc.id,
        language_id=translated_language_id,
    )
    if not (has_original_tags and has_translated_tags):
        return False

    has_entities = bool(
        await session.scalar(select(DocumentEntity.document_id).where(DocumentEntity.document_id == doc.id).limit(1))
    )
    if not has_entities:
        return False

    has_categories = bool(
        await session.scalar(
            select(DocumentCategory.document_id).where(DocumentCategory.document_id == doc.id).limit(1)
        )
    )
    if not has_categories:
        return False

    has_annotation = bool((doc.translated_summary or doc.original_summary or "").strip())
    if not has_annotation:
        return False

    return True


async def sync_document_statuses(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    assigned_by_id: uuid.UUID | None,
) -> None:
    doc = await session.get(Document, document_id)
    if doc is None:
        return

    # Phase B jobs (summary, categorize, tag-translated) run in parallel on separate workers.
    # This session may have loaded the document earlier; identity-map ``get`` does not pull
    # columns updated by other transactions. Flush local writes, then reload for checks.
    await session.flush()
    await session.refresh(doc)

    by_code = await _status_ids_by_code(
        session,
        required_codes=("new", "unprocessed", "processed"),
    )
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)
    keep_new = doc.created_at >= week_ago
    is_fully_populated = await _is_document_fully_populated(session, doc=doc)

    if keep_new:
        await session.execute(
            insert(DocumentStatusAssignment)
            .values(
                document_id=document_id,
                status_id=by_code["new"],
                assigned_by_id=assigned_by_id,
            )
            .on_conflict_do_nothing(
                index_elements=[DocumentStatusAssignment.document_id, DocumentStatusAssignment.status_id]
            )
        )
    else:
        await session.execute(
            delete(DocumentStatusAssignment).where(
                DocumentStatusAssignment.document_id == document_id,
                DocumentStatusAssignment.status_id == by_code["new"],
            )
        )

    if is_fully_populated:
        await session.execute(
            delete(DocumentStatusAssignment).where(
                DocumentStatusAssignment.document_id == document_id,
                DocumentStatusAssignment.status_id == by_code["unprocessed"],
            )
        )
        await session.execute(
            insert(DocumentStatusAssignment)
            .values(
                document_id=document_id,
                status_id=by_code["processed"],
                assigned_by_id=assigned_by_id,
            )
            .on_conflict_do_nothing(
                index_elements=[DocumentStatusAssignment.document_id, DocumentStatusAssignment.status_id]
            )
        )
    else:
        await session.execute(
            delete(DocumentStatusAssignment).where(
                DocumentStatusAssignment.document_id == document_id,
                DocumentStatusAssignment.status_id == by_code["processed"],
            )
        )
        await session.execute(
            insert(DocumentStatusAssignment)
            .values(
                document_id=document_id,
                status_id=by_code["unprocessed"],
                assigned_by_id=assigned_by_id,
            )
            .on_conflict_do_nothing(
                index_elements=[DocumentStatusAssignment.document_id, DocumentStatusAssignment.status_id]
            )
        )


async def get_document_by_source_url(session: AsyncSession, url: str) -> Document | None:
    norm = normalize_source_url(url)
    q = await session.execute(select(Document).where(Document.source_url == norm))
    return q.scalar_one_or_none()


def document_to_extract_response(
    doc: Document,
    *,
    from_cache: bool,
    statuses: list[DocumentStatusItem] | None = None,
    original_tags: list[DocumentTagItem] | None = None,
    translated_tags: list[DocumentTagItem] | None = None,
    entities_military_equipment: list[DocumentEntityItem] | None = None,
    entities_manufacturers: list[DocumentEntityItem] | None = None,
    entities_contracts: list[DocumentEntityItem] | None = None,
    categories: list[DocumentCategorizeItem] | None = None,
) -> DocumentExtractResponse:
    images: list[ImageInfo] = []
    for item in doc.extracted_images or []:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        images.append(
            ImageInfo(
                url=str(url),
                alt=item.get("alt"),
                title=item.get("title"),
            )
        )
    needs_review = False if doc.extract_needs_review is None else bool(doc.extract_needs_review)
    method = doc.extract_method or "unknown"
    quality = doc.extract_quality or "unknown"

    return DocumentExtractResponse(
        title=doc.title or None,
        translated_title=doc.translated_title,
        author=doc.extracted_author,
        date=doc.extracted_date,
        url=doc.source_url,
        text=doc.original_content,
        length=len(doc.original_content or ""),
        method=method,
        quality=quality,
        needs_review=needs_review,
        images=images,
        main_image=doc.extracted_main_image,
        document_id=doc.id,
        from_cache=from_cache,
        version=doc.version,
        published_at=doc.published_at,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        translated_content=doc.translated_content,
        original_summary=doc.original_summary,
        translated_summary=doc.translated_summary,
        original_summary_stale=bool(doc.original_summary_stale),
        translated_summary_stale=bool(doc.translated_summary_stale),
        statuses=statuses or [],
        original_tags=list(original_tags or []),
        translated_tags=list(translated_tags or []),
        entities_military_equipment=list(entities_military_equipment or []),
        entities_manufacturers=list(entities_manufacturers or []),
        entities_contracts=list(entities_contracts or []),
        categories=list(categories or []),
    )


async def create_document_after_extract(
    session: AsyncSession,
    *,
    norm_url: str,
    extract_payload: dict,
    created_by_id: uuid.UUID | None,
    document_type_code: str = "undefined",
) -> Document:
    text = extract_payload["text"]
    lang_code = _map_lang_for_db(await asyncio.to_thread(detect_language, text))
    ol_id = await language_id_by_code(session, lang_code)
    dt_id = await document_type_id_by_code(session, document_type_code)
    title = (extract_payload.get("title") or "").strip() or "Без названия"

    raw_author = extract_payload.get("author")
    extracted_author = (str(raw_author).strip()[:512] if raw_author else None) or None

    raw_date = extract_payload.get("date")
    extracted_date: str | None = None
    if raw_date is not None:
        ds = str(raw_date).strip()
        if ds:
            extracted_date = ds[:128]

    published_at = _published_at_from_extract_date(extracted_date)

    raw_method = extract_payload.get("method")
    extract_method = (str(raw_method).strip()[:64] if raw_method else None) or None

    raw_quality = extract_payload.get("quality")
    extract_quality = (str(raw_quality).strip()[:32] if raw_quality else None) or None

    nr = extract_payload.get("needs_review")
    extract_needs_review: bool | None = bool(nr) if nr is not None else None

    doc = Document(
        title=title[:512],
        original_content=text,
        original_language_id=ol_id,
        document_type_id=dt_id,
        source_url=norm_url,
        extracted_images=extract_payload.get("images") or [],
        extracted_main_image=extract_payload.get("main_image"),
        extracted_author=extracted_author,
        extracted_date=extracted_date,
        extract_method=extract_method,
        extract_quality=extract_quality,
        extract_needs_review=extract_needs_review,
        published_at=published_at,
        created_by_id=created_by_id,
        original_summary_stale=True,
        translated_summary_stale=True,
    )
    session.add(doc)
    await session.flush()
    await _attach_default_new_unprocessed_statuses(
        session,
        document_id=doc.id,
        assigned_by_id=created_by_id,
    )
    return doc


async def create_document_from_raw_text(
    session: AsyncSession,
    *,
    title: str,
    author: str,
    publication_date: date,
    text: str,
    created_by_id: uuid.UUID | None,
    document_type_code: str = "undefined",
    source_url: str | None = None,
    main_image: str | None = None,
) -> Document:
    stripped = text.strip()
    if not stripped:
        raise ValidationError("Текст документа не может быть пустым")

    title_clean = title.strip()
    if not title_clean:
        raise ValidationError("Заголовок не может быть пустым")

    author_clean = author.strip()
    if not author_clean:
        raise ValidationError("Автор не может быть пустым")

    code = document_type_code.strip()
    if not code:
        code = "undefined"
    try:
        dt_id = await document_type_id_by_code(session, code)
    except NoResultFound as exc:
        raise ValidationError(f"Неизвестный тип документа: {code!r}") from exc

    lang_code = _map_lang_for_db(await asyncio.to_thread(detect_language, stripped))
    ol_id = await language_id_by_code(session, lang_code)

    published_at = datetime(publication_date.year, publication_date.month, publication_date.day, tzinfo=UTC)
    extracted_date_str = publication_date.isoformat()[:128]

    main_image_clean = (main_image.strip()[:8192] if main_image and main_image.strip() else None) or None

    doc = Document(
        title=title_clean[:512],
        original_content=stripped,
        original_language_id=ol_id,
        document_type_id=dt_id,
        source_url=source_url,
        extracted_images=[],
        extracted_main_image=main_image_clean,
        extracted_author=author_clean[:512],
        extracted_date=extracted_date_str,
        extract_method="manual",
        extract_quality="manual",
        extract_needs_review=False,
        published_at=published_at,
        created_by_id=created_by_id,
        original_summary_stale=True,
        translated_summary_stale=True,
    )
    session.add(doc)
    await session.flush()
    await _attach_default_new_unprocessed_statuses(
        session,
        document_id=doc.id,
        assigned_by_id=created_by_id,
    )
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


async def delete_auto_document_tags(
    session: AsyncSession,
    document_id: uuid.UUID,
    *,
    language_id: uuid.UUID | None = None,
) -> None:
    manual_id = await _manual_ps_id(session)
    tag_ids_subquery = select(Tag.id)
    if language_id is not None:
        tag_ids_subquery = tag_ids_subquery.where(Tag.language_id == language_id)

    await session.execute(
        delete(DocumentTag).where(
            DocumentTag.document_id == document_id,
            DocumentTag.tag_id.in_(tag_ids_subquery),
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

    original_changed = body.original_content is not None and body.original_content != doc.original_content
    translated_changed = body.translated_content is not None and body.translated_content != doc.translated_content
    summary_changed = (body.original_summary is not None and body.original_summary != doc.original_summary) or (
        body.translated_summary is not None and body.translated_summary != doc.translated_summary
    )

    if original_changed:
        doc.original_summary_stale = body.original_summary is None
    if translated_changed:
        doc.translated_summary_stale = body.translated_summary is None

    if body.title is not None:
        doc.title = body.title.strip()[:512] or doc.title
    if body.original_content is not None:
        doc.original_content = body.original_content
    if body.translated_content is not None:
        doc.translated_content = body.translated_content
    if body.original_summary is not None:
        doc.original_summary = body.original_summary
        doc.original_summary_stale = False
    if body.translated_summary is not None:
        doc.translated_summary = body.translated_summary
        doc.translated_summary_stale = False

    doc.version = (doc.version or 1) + 1
    doc.locked_by_id = None
    doc.locked_at = None
    doc.lock_expires_at = None
    doc.updated_at = now

    if original_changed or translated_changed:
        await invalidate_auto_derivatives(session, document_id)
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=user_id,
    )

    embed_stages: list[EmbeddingStage] = []
    if original_changed:
        embed_stages.append(EmbeddingStage.ORIGINAL)
    if translated_changed:
        embed_stages.append(EmbeddingStage.TRANSLATED)
    if summary_changed:
        embed_stages.append(EmbeddingStage.ANNOTATION)
    if embed_stages:
        await embed_document_stages_if_stale(
            session,
            document_id=document_id,
            stages=tuple(embed_stages),
        )
    return doc


async def update_document_metadata(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    body: DocumentMetadataUpdateRequest,
) -> Document:
    doc = await get_document_for_update(session, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    if body.title is not None:
        doc.title = body.title.strip()[:512] or doc.title
    if body.translated_title is not None:
        tt = body.translated_title.strip()
        doc.translated_title = tt[:512] if tt else None
    if body.author is not None:
        author = body.author.strip()
        doc.extracted_author = author[:512] if author else None
    if body.date is not None:
        date = body.date.strip()
        doc.extracted_date = date[:128] if date else None
    if body.source_url is not None:
        doc.source_url = normalize_source_url(str(body.source_url))
    if body.main_image is not None:
        doc.extracted_main_image = body.main_image.strip() or None
    if body.images is not None:
        doc.extracted_images = [
            {
                "url": item.url.strip(),
                "alt": (item.alt.strip() if item.alt else None),
                "title": (item.title.strip() if item.title else None),
            }
            for item in body.images
            if item.url.strip()
        ]

    doc.updated_at = datetime.now(UTC)
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


async def _fill_translated_title_after_body_translation(doc: Document, *, target_lang: str) -> None:
    """После успешного перевода текста — перевод заголовка на тот же target_lang. Ошибки LLM не откатывают перевод тела."""
    raw = (doc.title or "").strip()
    if not raw:
        return
    try:
        out = await translate_text(raw, target_lang=target_lang, stream=False)
    except Exception:
        logger.warning(
            "translate_title_after_body_failed",
            exc_info=True,
            extra={"document_id": str(doc.id)},
        )
        return
    if not isinstance(out, str):
        return
    st = out.strip()
    doc.translated_title = st[:512] if st else None


async def persist_document_translation(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    translated_text: str,
    target_lang: str,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    if track_job:
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
    else:
        tl_id = await language_id_by_code(session, target_lang)
        doc.translated_content = translated_text
        doc.translated_language_id = tl_id
        doc.translated_summary_stale = True
    await _fill_translated_title_after_body_translation(doc, target_lang=target_lang)
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    await embed_document_stages_if_stale(
        session,
        document_id=document_id,
        stages=(EmbeddingStage.TRANSLATED,),
    )
    return doc


async def run_translate_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    target_lang: str,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
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
        track_job=track_job,
    )


async def run_translate_document_title(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    target_lang: str,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")
    raw_title = (doc.title or "").strip()
    if not raw_title:
        raise ValidationError("Пустой заголовок для перевода")

    translated = await translate_text(raw_title, target_lang=target_lang, stream=False)
    if not isinstance(translated, str):
        raise ValidationError("Ожидалась строка перевода заголовка")
    tt = translated.strip()[:512] if translated.strip() else None

    if track_job:
        async with processing_job(
            session,
            document_id=document_id,
            job_type=JobType.TRANSLATE_TITLE,
            model_name=settings.model_translation,
            provider=None,
            started_by_id=started_by_id,
            llm_task_for_provider=LLMTask.TRANSLATION,
        ):
            doc.translated_title = tt
    else:
        doc.translated_title = tt

    doc.updated_at = datetime.now(UTC)
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    return doc


async def run_tag_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    max_tags: int,
    use_translation: bool,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
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

    if track_job:
        job_ctx = processing_job(
            session,
            document_id=document_id,
            job_type=JobType.TAG,
            model_name=settings.model_tagging,
            provider=None,
            started_by_id=started_by_id,
            llm_task_for_provider=LLMTask.TAGGING,
        )
    else:
        job_ctx = nullcontext()

    async with job_ctx:
        await delete_auto_document_tags(session, document_id, language_id=lang_id)
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
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    return doc


async def run_entity_extract_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
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

    if track_job:
        job_ctx = processing_job(
            session,
            document_id=document_id,
            job_type=JobType.ENTITY_EXTRACT,
            model_name=settings.model_entity_extraction,
            provider=None,
            started_by_id=started_by_id,
            llm_task_for_provider=LLMTask.ENTITY_EXTRACTION,
        )
    else:
        job_ctx = nullcontext()

    async with job_ctx:
        await delete_auto_document_entities(session, document_id)
        raw = await extract_entities(src)
        military_equipment = [name.strip() for name in raw.get("military_equipment", []) if name and name.strip()]
        manufacturers = [name.strip() for name in raw.get("manufacturers", []) if name and name.strip()]
        contracts = [name.strip() for name in raw.get("contracts", []) if name and name.strip()]

        if not military_equipment:
            military_equipment = [NOT_FOUND_ENTITY_NAME]
        if not manufacturers:
            manufacturers = [NOT_FOUND_ENTITY_NAME]
        if not contracts:
            contracts = [NOT_FOUND_ENTITY_NAME]

        for name in dict.fromkeys(military_equipment):
            eid = await _get_or_create_entity(session, name, et_mil, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
        for name in dict.fromkeys(manufacturers):
            eid = await _get_or_create_entity(session, name, et_man, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
        for name in dict.fromkeys(contracts):
            eid = await _get_or_create_entity(session, name, et_con, lang_id)
            session.add(
                DocumentEntity(
                    document_id=document_id,
                    entity_id=eid,
                    prediction_source_id=llm_ps,
                ),
            )
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    return doc


async def run_categorize_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
) -> tuple[Document, list[DocumentCategorizeItem]]:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    translated = (doc.translated_content or "").strip()
    original = (doc.original_content or "").strip()
    if translated:
        src = doc.translated_content or ""
        text_source: Literal["original", "translated"] = "translated"
    elif original:
        src = doc.original_content
        text_source = "original"
    else:
        raise ValidationError("Пустой текст документа")

    parent = aliased(Category)
    q = await session.execute(
        select(
            Category.id,
            Category.code,
            Category.name,
            Category.name_ru,
            Category.description,
            Category.description_ru,
            Category.level,
            parent.id.label("parent_id"),
            parent.code.label("parent_code"),
            parent.name.label("parent_name"),
            parent.name_ru.label("parent_name_ru"),
        )
        .outerjoin(parent, parent.id == Category.parent_id)
        .where(
            Category.is_active.is_(True),
            Category.level == 3,
        ),
    )
    pairs: list[tuple[str, str]] = []
    meta_by_code: dict[
        str,
        tuple[
            uuid.UUID,
            str,
            str | None,
            int,
            uuid.UUID | None,
            str | None,
            str | None,
            str | None,
        ],
    ] = {}
    for (
        cid,
        code,
        name,
        name_ru,
        description,
        description_ru,
        level,
        parent_id,
        parent_code,
        parent_name,
        parent_name_ru,
    ) in q.all():
        label = f"{name_ru} — {name}" if name_ru else name
        desc = (description_ru or description or "").strip()
        if desc:
            if len(desc) > 320:
                desc = desc[:317] + "..."
            label = f"{label}. {desc}"
        pairs.append((code, label))
        meta_by_code[code] = (
            cid,
            name,
            name_ru,
            level,
            parent_id,
            parent_code,
            parent_name,
            parent_name_ru,
        )

    llm_ps = await _llm_ps_id(session)
    assigned: list[DocumentCategorizeItem] = []

    if track_job:
        job_ctx = processing_job(
            session,
            document_id=document_id,
            job_type=JobType.CATEGORIZE,
            model_name=settings.model_categorization,
            provider=None,
            started_by_id=started_by_id,
            llm_task_for_provider=LLMTask.CATEGORIZATION,
        )
    else:
        job_ctx = nullcontext()

    async with job_ctx:
        await delete_auto_document_categories(session, document_id)
        items = await categorize_text(src, pairs)
        unique_items_by_category: dict[
            uuid.UUID,
            tuple[str, str, str | None, int, uuid.UUID | None, str | None, str | None, str | None, Decimal],
        ] = {}
        for it in items:
            code = it["code"]
            meta = meta_by_code.get(code)
            if meta is None:
                continue
            cid, name, name_ru, level, parent_id, parent_code, parent_name, parent_name_ru = meta
            conf_f = float(it.get("confidence", 0.5))
            conf = Decimal(str(conf_f))
            prev = unique_items_by_category.get(cid)
            if prev is None or conf > prev[-1]:
                unique_items_by_category[cid] = (
                    code,
                    name,
                    name_ru,
                    level,
                    parent_id,
                    parent_code,
                    parent_name,
                    parent_name_ru,
                    conf,
                )

        if unique_items_by_category:
            stmt = insert(DocumentCategory).values(
                [
                    {
                        "document_id": document_id,
                        "category_id": cid,
                        "confidence": payload[-1],
                        "prediction_source_id": llm_ps,
                    }
                    for cid, payload in unique_items_by_category.items()
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[DocumentCategory.document_id, DocumentCategory.category_id],
                set_={
                    "confidence": stmt.excluded.confidence,
                    "prediction_source_id": stmt.excluded.prediction_source_id,
                },
            )
            await session.execute(stmt)
        else:
            fallback = await session.execute(
                select(
                    Category.id,
                    Category.code,
                    Category.name,
                    Category.name_ru,
                    Category.level,
                ).where(Category.code == FALLBACK_CATEGORY_CODE)
            )
            fallback_row = fallback.first()
            if fallback_row is None:
                raise ValidationError(
                    f"Не найдена fallback-категория '{FALLBACK_CATEGORY_CODE}'. Примените seed_reference_data."
                )

            fallback_conf = Decimal("1.0")
            stmt = insert(DocumentCategory).values(
                [
                    {
                        "document_id": document_id,
                        "category_id": fallback_row.id,
                        "confidence": fallback_conf,
                        "prediction_source_id": llm_ps,
                    }
                ]
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[DocumentCategory.document_id, DocumentCategory.category_id],
                set_={
                    "confidence": stmt.excluded.confidence,
                    "prediction_source_id": stmt.excluded.prediction_source_id,
                },
            )
            await session.execute(stmt)
            unique_items_by_category[fallback_row.id] = (
                fallback_row.code,
                fallback_row.name,
                fallback_row.name_ru,
                fallback_row.level,
                None,
                None,
                None,
                None,
                fallback_conf,
            )

        for cid, payload in unique_items_by_category.items():
            (
                code,
                name,
                name_ru,
                level,
                parent_id,
                parent_code,
                parent_name,
                parent_name_ru,
                conf,
            ) = payload
            assigned.append(
                DocumentCategorizeItem(
                    category_id=cid,
                    code=code,
                    name=name,
                    name_ru=name_ru,
                    level=level,
                    parent_id=parent_id,
                    parent_code=parent_code,
                    parent_name=parent_name,
                    parent_name_ru=parent_name_ru,
                    confidence=float(conf),
                    prediction_source_code="llm",
                    text_source=text_source,
                ),
            )

    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    assigned.sort(key=lambda x: x.confidence, reverse=True)
    return doc, assigned


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
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    await embed_document_stages_if_stale(
        session,
        document_id=document_id,
        stages=(EmbeddingStage.ANNOTATION,),
    )
    return doc


async def persist_document_summary(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    annotation: str,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
) -> Document:
    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    if track_job:
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
    else:
        # Summarizer prompts produce Russian; store in translated_summary only.
        doc.translated_summary = annotation
        doc.translated_summary_stale = False
    await sync_document_statuses(
        session,
        document_id=document_id,
        assigned_by_id=started_by_id,
    )
    await embed_document_stages_if_stale(
        session,
        document_id=document_id,
        stages=(EmbeddingStage.ANNOTATION,),
    )
    return doc


async def run_summary_document(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    source: SummarySource,
    started_by_id: uuid.UUID | None,
    track_job: bool = True,
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
        track_job=track_job,
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
