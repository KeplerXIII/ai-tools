from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_user,
    get_current_user_optional,
    get_optional_started_by_id,
)
from app.api.error_mapping import map_app_error
from app.domain.errors import AppError, ValidationError
from app.infrastructure.db.models import Document, DocumentStatus, DocumentStatusAssignment, User
from app.infrastructure.db.models import DocumentEntity, DocumentTag, Entity, EntityType, Tag
from app.infrastructure.db.session import AsyncSessionLocal, get_db
from app.schemas.documents import (
    DocumentCategorizeResponse,
    DocumentEntityAssignRequest,
    DocumentEntityItem,
    DocumentStatusCatalogItem,
    DocumentExtractResponse,
    DocumentEntitiesExtractResponse,
    DocumentRefineSummaryRequest,
    DocumentRefineSummaryResponse,
    DocumentStatusAssignRequest,
    DocumentStatusesResponse,
    DocumentStatusItem,
    DocumentSummaryRequest,
    DocumentSummaryResponse,
    DocumentTagAssignRequest,
    DocumentTagItem,
    DocumentTagRequest,
    DocumentTagsResponse,
    DocumentTranslateRequest,
    DocumentUpdateRequest,
    ExtractUrlPersistRequest,
    SummarySource,
)
from app.services.documents.db_refs import entity_type_id_by_code, language_id_by_code, prediction_source_id
from app.services.documents.document_pipeline import (
    acquire_edit_lock,
    create_document_after_extract,
    document_to_extract_response,
    get_document_by_source_url,
    persist_document_refined_summary,
    persist_document_summary,
    persist_document_translation,
    record_completed_extract_job,
    run_categorize_document,
    run_entity_extract_document,
    run_refine_document,
    run_summary_document,
    run_tag_document,
    run_translate_document,
    save_document_after_edit,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.llm.summarizer import refine_summary, summarize_text
from app.services.llm.translator import detect_language, translate_text
from app.services.parsing.extractor import download_html, extract_article_text
router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

DOCUMENT_ENTITY_TYPE_CODES = frozenset({"military_equipment", "manufacturer", "contract"})
TAG_LANGUAGE_SCOPES = frozenset({"original", "translated"})


async def _prepare_write_session(db: AsyncSession) -> None:
    """Depends() уже мог выполнить SELECT — сессия в autobegin; иначе db.begin() даст InvalidRequestError."""
    await db.rollback()


def _sse_data(payload: str) -> bytes:
    # SSE requires each logical line to be prefixed with `data:`.
    lines = payload.splitlines() or [""]
    body = "".join(f"data: {line}\n" for line in lines)
    return f"{body}\n".encode("utf-8")


def _sse_error(message: str) -> bytes:
    safe = message.replace("\n", " ").strip()
    return f"event: error\ndata: {safe}\n\n".encode("utf-8")


async def _get_document_status_items(db: AsyncSession, document_id: UUID) -> list[DocumentStatusItem]:
    result = await db.execute(
        select(
            DocumentStatus.code,
            DocumentStatus.name_ru,
            DocumentStatus.description,
            DocumentStatusAssignment.assigned_at,
            DocumentStatusAssignment.assigned_by_id,
        )
        .join(DocumentStatus, DocumentStatus.id == DocumentStatusAssignment.status_id)
        .where(DocumentStatusAssignment.document_id == document_id)
        .order_by(DocumentStatusAssignment.assigned_at.desc(), DocumentStatus.code.asc())
    )
    return [
        DocumentStatusItem(
            code=row.code,
            name_ru=row.name_ru,
            description=row.description,
            assigned_at=row.assigned_at,
            assigned_by_id=row.assigned_by_id,
        )
        for row in result
    ]


async def _get_document_tags(
    db: AsyncSession,
    doc: Document,
) -> tuple[list[DocumentTagItem], list[DocumentTagItem]]:
    rows = await db.execute(
        select(Tag.id, Tag.name, Tag.language_id)
        .join(DocumentTag, DocumentTag.tag_id == Tag.id)
        .where(DocumentTag.document_id == doc.id)
        .order_by(Tag.name.asc())
    )
    original_tags: list[DocumentTagItem] = []
    translated_tags: list[DocumentTagItem] = []
    for row in rows:
        name = row.name
        if not name:
            continue
        item = DocumentTagItem(id=row.id, name=name)
        if row.language_id == doc.original_language_id:
            original_tags.append(item)
        elif doc.translated_language_id is not None and row.language_id == doc.translated_language_id:
            translated_tags.append(item)
        else:
            original_tags.append(item)
    return original_tags, translated_tags


async def _tag_catalog_language_id(db: AsyncSession, doc: Document, scope: str) -> UUID:
    if scope == "original":
        return doc.original_language_id
    if scope == "translated":
        if doc.translated_language_id is not None:
            return doc.translated_language_id
        return await language_id_by_code(db, "ru")
    raise HTTPException(status_code=400, detail="Недопустимый язык для каталога тегов")


async def _document_allowed_tag_language_ids(db: AsyncSession, doc: Document) -> set[UUID]:
    out: set[UUID] = {doc.original_language_id}
    if doc.translated_language_id is not None:
        out.add(doc.translated_language_id)
    else:
        out.add(await language_id_by_code(db, "ru"))
    return out


async def _get_document_entities(
    db: AsyncSession,
    document_id: UUID,
) -> tuple[list[DocumentEntityItem], list[DocumentEntityItem], list[DocumentEntityItem]]:
    rows = await db.execute(
        select(EntityType.code, Entity.id, Entity.name)
        .select_from(DocumentEntity)
        .join(Entity, Entity.id == DocumentEntity.entity_id)
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .where(DocumentEntity.document_id == document_id)
        .order_by(EntityType.code.asc(), Entity.name.asc())
    )
    military_equipment: list[DocumentEntityItem] = []
    manufacturers: list[DocumentEntityItem] = []
    contracts: list[DocumentEntityItem] = []
    for row in rows:
        name = row.name
        if not name:
            continue
        code = row.code
        item = DocumentEntityItem(id=row.id, name=name)
        if code == "military_equipment":
            military_equipment.append(item)
        elif code == "manufacturer":
            manufacturers.append(item)
        elif code == "contract":
            contracts.append(item)
    return military_equipment, manufacturers, contracts




@router.post("/extract-url", response_model=DocumentExtractResponse)
async def extract_url_persist(
    payload: ExtractUrlPersistRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    url_str = str(payload.url)
    norm = normalize_source_url(url_str)
    existing = await get_document_by_source_url(db, url_str)
    if existing:
        # Backfill image metadata for old cached documents created before image persistence.
        if existing.source_url and not existing.extracted_images and not existing.extracted_main_image:
            try:
                html = await download_html(url_str)
                refreshed = await extract_article_text(html, url_str)
                extracted_images = refreshed.get("images") or []
                extracted_main_image = refreshed.get("main_image")
                if extracted_images or extracted_main_image:
                    await _prepare_write_session(db)
                    async with db.begin():
                        existing.extracted_images = extracted_images
                        existing.extracted_main_image = extracted_main_image
            except Exception:
                logger.exception("failed to backfill extract images for cached document", extra={"url": url_str})
        statuses = await _get_document_status_items(db, existing.id)
        original_tags, translated_tags = await _get_document_tags(db, existing)
        entities_military_equipment, entities_manufacturers, entities_contracts = await _get_document_entities(
            db, existing.id
        )
        return document_to_extract_response(
            existing,
            from_cache=True,
            statuses=statuses,
            original_tags=original_tags,
            translated_tags=translated_tags,
            entities_military_equipment=entities_military_equipment,
            entities_manufacturers=entities_manufacturers,
            entities_contracts=entities_contracts,
        )

    t0 = time.perf_counter()
    html = await download_html(url_str)
    data = await extract_article_text(html, url_str)
    duration_ms = int((time.perf_counter() - t0) * 1000)

    created_by_id = user.id if user else None
    await _prepare_write_session(db)
    try:
        async with db.begin():
            doc = await create_document_after_extract(
                db,
                norm_url=norm,
                extract_payload=data,
                created_by_id=created_by_id,
                document_type_code=payload.document_type_code,
            )
            await record_completed_extract_job(
                db,
                document_id=doc.id,
                duration_ms=duration_ms,
                started_by_id=created_by_id,
            )
            doc_id = doc.id
    except ValidationError as exc:
        await db.rollback()
        _handle(exc)
    except IntegrityError:
        await db.rollback()
        existing2 = await get_document_by_source_url(db, url_str)
        if existing2:
            statuses = await _get_document_status_items(db, existing2.id)
            original_tags, translated_tags = await _get_document_tags(db, existing2)
            entities_military_equipment, entities_manufacturers, entities_contracts = await _get_document_entities(
                db, existing2.id
            )
            return document_to_extract_response(
                existing2,
                from_cache=True,
                statuses=statuses,
                original_tags=original_tags,
                translated_tags=translated_tags,
                entities_military_equipment=entities_military_equipment,
                entities_manufacturers=entities_manufacturers,
                entities_contracts=entities_contracts,
            )
        raise

    created_doc = await db.get(Document, doc_id)
    if created_doc is None:
        raise HTTPException(status_code=500, detail="Не удалось загрузить созданный документ")
    statuses_new = await _get_document_status_items(db, doc_id)
    return document_to_extract_response(
        created_doc,
        from_cache=False,
        statuses=statuses_new,
        original_tags=[],
        translated_tags=[],
        entities_military_equipment=[],
        entities_manufacturers=[],
        entities_contracts=[],
    )


def _handle(exc: AppError):
    raise map_app_error(exc) from exc


@router.get("/statuses/catalog", response_model=list[DocumentStatusCatalogItem])
async def document_statuses_catalog(
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(DocumentStatus.code, DocumentStatus.name_ru, DocumentStatus.description).order_by(
            DocumentStatus.name_ru.asc()
        )
    )
    return [
        DocumentStatusCatalogItem(
            code=row.code,
            name_ru=row.name_ru,
            description=row.description,
        )
        for row in rows
    ]


@router.get("/{document_id}/statuses", response_model=DocumentStatusesResponse)
async def document_statuses(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    statuses = await _get_document_status_items(db, document_id)
    return DocumentStatusesResponse(document_id=document_id, statuses=statuses)


@router.post("/{document_id}/statuses")
async def assign_document_status(
    document_id: UUID,
    payload: DocumentStatusAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    status_code = payload.code.strip().lower()
    if not status_code:
        raise HTTPException(status_code=400, detail="Код статуса не должен быть пустым")

    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    status_id = await db.scalar(select(DocumentStatus.id).where(DocumentStatus.code == status_code))
    if status_id is None:
        raise HTTPException(status_code=404, detail="Статус не найден")

    await _prepare_write_session(db)
    async with db.begin():
        if status_code == "processed":
            unproc_id = await db.scalar(
                select(DocumentStatus.id).where(DocumentStatus.code == "unprocessed")
            )
            if unproc_id is not None:
                await db.execute(
                    delete(DocumentStatusAssignment).where(
                        DocumentStatusAssignment.document_id == document_id,
                        DocumentStatusAssignment.status_id == unproc_id,
                    )
                )
        elif status_code == "unprocessed":
            proc_id = await db.scalar(select(DocumentStatus.id).where(DocumentStatus.code == "processed"))
            if proc_id is not None:
                await db.execute(
                    delete(DocumentStatusAssignment).where(
                        DocumentStatusAssignment.document_id == document_id,
                        DocumentStatusAssignment.status_id == proc_id,
                    )
                )
        stmt = insert(DocumentStatusAssignment).values(
            document_id=document_id,
            status_id=status_id,
            assigned_by_id=user_id,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[DocumentStatusAssignment.document_id, DocumentStatusAssignment.status_id]
        )
        await db.execute(stmt)
    return {"ok": True, "document_id": str(document_id), "status_code": status_code}


@router.delete("/{document_id}/statuses/{status_code}")
async def remove_document_status(
    document_id: UUID,
    status_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    normalized_code = status_code.strip().lower()
    if not normalized_code:
        raise HTTPException(status_code=400, detail="Код статуса не должен быть пустым")

    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    status_id = await db.scalar(select(DocumentStatus.id).where(DocumentStatus.code == normalized_code))
    if status_id is None:
        raise HTTPException(status_code=404, detail="Статус не найден")

    await _prepare_write_session(db)
    async with db.begin():
        await db.execute(
            delete(DocumentStatusAssignment).where(
                DocumentStatusAssignment.document_id == document_id,
                DocumentStatusAssignment.status_id == status_id,
            )
        )
    return {"ok": True, "document_id": str(document_id), "status_code": normalized_code}


@router.post("/{document_id}/translate/stream")
async def document_translate_stream(
    document_id: UUID,
    payload: DocumentTranslateRequest,
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
):
    target_lang = payload.target_lang
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Документ не найден")
        if not doc.original_content.strip():
            raise HTTPException(status_code=400, detail="Пустой исходный текст")
        source_text = doc.original_content
    source_lang = await asyncio.to_thread(detect_language, source_text)

    async def body():
        try:
            stream = await translate_text(source_text, target_lang=target_lang, stream=True)
        except AppError as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        parts: list[str] = []
        try:
            async for chunk in stream:
                s = chunk if isinstance(chunk, str) else str(chunk)
                parts.append(s)
                yield _sse_data(s)
                await asyncio.sleep(0)
        except Exception as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        full = "".join(parts)
        try:
            async with AsyncSessionLocal() as w_session:
                async with w_session.begin():
                    await persist_document_translation(
                        w_session,
                        document_id=document_id,
                        translated_text=full,
                        target_lang=target_lang,
                        started_by_id=started_by_id,
                    )
        except Exception as exc:
            logger.exception("persist translation after stream failed")
            yield _sse_error(f"[persist_error] {exc}")
            return
        yield _sse_data("[DONE]")

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Source-Lang": source_lang,
            "X-Target-Lang": target_lang,
            "X-Document-Id": str(document_id),
        },
    )


@router.post("/{document_id}/translate")
async def document_translate(
    document_id: UUID,
    payload: DocumentTranslateRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await run_translate_document(
                db,
                document_id=document_id,
                target_lang=payload.target_lang,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}


@router.get("/{document_id}/tags/catalog", response_model=list[DocumentTagItem])
async def document_tags_catalog(
    document_id: UUID,
    language_scope: str = Query(..., min_length=1, max_length=16),
    db: AsyncSession = Depends(get_db),
):
    normalized = language_scope.strip().lower()
    if normalized not in TAG_LANGUAGE_SCOPES:
        raise HTTPException(status_code=400, detail="Укажите language_scope: original или translated")

    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    lang_id = await _tag_catalog_language_id(db, doc, normalized)

    assigned_rows = await db.execute(
        select(DocumentTag.tag_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(
            DocumentTag.document_id == document_id,
            Tag.language_id == lang_id,
        )
    )
    assigned_ids = {row[0] for row in assigned_rows}

    stmt = select(Tag.id, Tag.name).where(Tag.language_id == lang_id).order_by(Tag.name.asc())
    if assigned_ids:
        stmt = stmt.where(Tag.id.not_in(assigned_ids))

    rows = await db.execute(stmt)
    return [DocumentTagItem(id=row.id, name=row.name) for row in rows]


@router.get("/{document_id}/tags", response_model=DocumentTagsResponse)
async def get_document_tags_snapshot(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    original_tags, translated_tags = await _get_document_tags(db, doc)
    return DocumentTagsResponse(
        document_id=document_id,
        original_tags=original_tags,
        translated_tags=translated_tags,
    )


@router.post("/{document_id}/tags/assign")
async def assign_document_tag(
    document_id: UUID,
    payload: DocumentTagAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    tag_row = await db.get(Tag, payload.tag_id)
    if tag_row is None:
        raise HTTPException(status_code=404, detail="Тег не найден")

    allowed_lang = await _document_allowed_tag_language_ids(db, doc)
    if tag_row.language_id not in allowed_lang:
        raise HTTPException(status_code=400, detail="Язык тега не соответствует документу")

    manual_id = await prediction_source_id(db, "manual")
    await _prepare_write_session(db)
    async with db.begin():
        stmt = insert(DocumentTag).values(
            document_id=document_id,
            tag_id=payload.tag_id,
            prediction_source_id=manual_id,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[DocumentTag.document_id, DocumentTag.tag_id],
        )
        await db.execute(stmt)
    return {"ok": True, "document_id": str(document_id), "tag_id": str(payload.tag_id)}


@router.delete("/{document_id}/tags/{tag_id}")
async def remove_document_tag(
    document_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    await _prepare_write_session(db)
    async with db.begin():
        await db.execute(
            delete(DocumentTag).where(
                DocumentTag.document_id == document_id,
                DocumentTag.tag_id == tag_id,
            )
        )
    return {"ok": True, "document_id": str(document_id), "tag_id": str(tag_id)}


@router.post("/{document_id}/tags")
async def document_tags(
    document_id: UUID,
    payload: DocumentTagRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await run_tag_document(
                db,
                document_id=document_id,
                max_tags=payload.max_tags,
                use_translation=payload.use_translation,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}


@router.get("/{document_id}/entities/catalog", response_model=list[DocumentEntityItem])
async def document_entities_catalog(
    document_id: UUID,
    entity_type_code: str = Query(..., min_length=1, max_length=64),
    db: AsyncSession = Depends(get_db),
):
    normalized = entity_type_code.strip().lower()
    if normalized not in DOCUMENT_ENTITY_TYPE_CODES:
        raise HTTPException(status_code=400, detail="Неизвестный тип сущности")

    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    et_id = await entity_type_id_by_code(db, normalized)

    assigned_rows = await db.execute(
        select(DocumentEntity.entity_id)
        .join(Entity, Entity.id == DocumentEntity.entity_id)
        .where(
            DocumentEntity.document_id == document_id,
            Entity.entity_type_id == et_id,
        )
    )
    assigned_ids = {row[0] for row in assigned_rows}

    stmt = (
        select(Entity.id, Entity.name)
        .where(
            Entity.entity_type_id == et_id,
            Entity.language_id == doc.original_language_id,
        )
        .order_by(Entity.name.asc())
    )
    if assigned_ids:
        stmt = stmt.where(Entity.id.not_in(assigned_ids))

    rows = await db.execute(stmt)
    return [DocumentEntityItem(id=row.id, name=row.name) for row in rows]


@router.get("/{document_id}/entities", response_model=DocumentEntitiesExtractResponse)
async def get_document_entities_snapshot(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    military_equipment, manufacturers, contracts = await _get_document_entities(db, document_id)
    return DocumentEntitiesExtractResponse(
        document_id=document_id,
        military_equipment=military_equipment,
        manufacturers=manufacturers,
        contracts=contracts,
    )


@router.post("/{document_id}/entities/assign")
async def assign_document_entity(
    document_id: UUID,
    payload: DocumentEntityAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    ent = await db.get(Entity, payload.entity_id)
    if ent is None:
        raise HTTPException(status_code=404, detail="Сущность не найдена")
    if ent.language_id != doc.original_language_id:
        raise HTTPException(status_code=400, detail="Язык сущности не совпадает с языком документа")

    manual_id = await prediction_source_id(db, "manual")
    await _prepare_write_session(db)
    async with db.begin():
        stmt = insert(DocumentEntity).values(
            document_id=document_id,
            entity_id=payload.entity_id,
            prediction_source_id=manual_id,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[DocumentEntity.document_id, DocumentEntity.entity_id],
        )
        await db.execute(stmt)
    return {"ok": True, "document_id": str(document_id), "entity_id": str(payload.entity_id)}


@router.delete("/{document_id}/entities/{entity_id}")
async def remove_document_entity(
    document_id: UUID,
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    await _prepare_write_session(db)
    async with db.begin():
        await db.execute(
            delete(DocumentEntity).where(
                DocumentEntity.document_id == document_id,
                DocumentEntity.entity_id == entity_id,
            )
        )
    return {"ok": True, "document_id": str(document_id), "entity_id": str(entity_id)}


@router.post("/{document_id}/entities", response_model=DocumentEntitiesExtractResponse)
async def document_entities(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await run_entity_extract_document(
                db,
                document_id=document_id,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    military_equipment, manufacturers, contracts = await _get_document_entities(db, document_id)
    return DocumentEntitiesExtractResponse(
        document_id=document_id,
        military_equipment=military_equipment,
        manufacturers=manufacturers,
        contracts=contracts,
    )


@router.post("/{document_id}/categorize", response_model=DocumentCategorizeResponse)
async def document_categorize(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            _, categories = await run_categorize_document(
                db,
                document_id=document_id,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return DocumentCategorizeResponse(document_id=document_id, categories=categories)


@router.post("/{document_id}/summary/refine", response_model=DocumentRefineSummaryResponse)
async def document_summary_refine(
    document_id: UUID,
    payload: DocumentRefineSummaryRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            _, refined = await run_refine_document(
                db,
                document_id=document_id,
                source=payload.source,
                user_instruction=payload.user_instruction,
                mode=payload.mode,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return DocumentRefineSummaryResponse(refined_summary=refined, document_id=document_id)


@router.post("/{document_id}/summary/refine/stream")
async def document_summary_refine_stream(
    document_id: UUID,
    payload: DocumentRefineSummaryRequest,
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
):
    source = payload.source
    mode = payload.mode
    user_instruction = payload.user_instruction

    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Документ не найден")
        if source == SummarySource.original:
            article = doc.original_content
        else:
            article = doc.translated_content or ""
        summary = doc.translated_summary or doc.original_summary or ""
        if not article.strip():
            raise HTTPException(status_code=400, detail="Нет текста статьи")
        if not summary.strip():
            raise HTTPException(
                status_code=400,
                detail="Нет аннотации для уточнения — сначала сгенерируйте summary",
            )

    async def body():
        try:
            stream = await refine_summary(
                article_text=article,
                summary=summary,
                user_instruction=user_instruction,
                mode=mode,
                stream=True,
            )
        except AppError as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        parts: list[str] = []
        try:
            async for chunk in stream:
                s = chunk if isinstance(chunk, str) else str(chunk)
                parts.append(s)
                yield _sse_data(s)
                await asyncio.sleep(0)
        except Exception as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        full = "".join(parts)
        try:
            async with AsyncSessionLocal() as w_session:
                async with w_session.begin():
                    await persist_document_refined_summary(
                        w_session,
                        document_id=document_id,
                        source=source,
                        refined_annotation=full,
                        started_by_id=started_by_id,
                    )
        except Exception as exc:
            logger.exception("persist refined summary after stream failed")
            yield _sse_error(f"[persist_error] {exc}")
            return
        yield _sse_data("[DONE]")

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Document-Id": str(document_id),
            "X-Summary-Source": source.value,
        },
    )


@router.post("/{document_id}/summary", response_model=DocumentSummaryResponse)
async def document_summary(
    document_id: UUID,
    payload: DocumentSummaryRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            _, ann = await run_summary_document(
                db,
                document_id=document_id,
                source=payload.source,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return DocumentSummaryResponse(annotation=ann, document_id=document_id)


@router.post("/{document_id}/summary/stream")
async def document_summary_stream(
    document_id: UUID,
    payload: DocumentSummaryRequest,
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
):
    source = payload.source
    async with AsyncSessionLocal() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="Документ не найден")
        if source == SummarySource.original:
            source_text = doc.original_content
        else:
            source_text = doc.translated_content or ""
        if not source_text.strip():
            raise HTTPException(status_code=400, detail="Нет текста для аннотации")

    async def body():
        try:
            stream = await summarize_text(source_text, stream=True)
        except AppError as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        parts: list[str] = []
        try:
            async for chunk in stream:
                s = chunk if isinstance(chunk, str) else str(chunk)
                parts.append(s)
                yield _sse_data(s)
                await asyncio.sleep(0)
        except Exception as exc:
            yield _sse_error(f"[stream_error] {exc}")
            return
        full = "".join(parts)
        try:
            async with AsyncSessionLocal() as w_session:
                async with w_session.begin():
                    await persist_document_summary(
                        w_session,
                        document_id=document_id,
                        source=source,
                        annotation=full,
                        started_by_id=started_by_id,
                    )
        except Exception as exc:
            logger.exception("persist summary after stream failed")
            yield _sse_error(f"[persist_error] {exc}")
            return
        yield _sse_data("[DONE]")

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Document-Id": str(document_id),
            "X-Summary-Source": source.value,
        },
    )


@router.post("/{document_id}/lock")
async def document_lock(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await acquire_edit_lock(db, document_id=document_id, user_id=user_id)
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}


@router.put("/{document_id}")
async def document_save(
    document_id: UUID,
    payload: DocumentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await save_document_after_edit(
                db,
                document_id=document_id,
                user_id=user_id,
                body=payload,
            )
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}
