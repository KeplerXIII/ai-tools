from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import (
    get_current_user,
    get_current_user_optional,
    get_optional_started_by_id,
)
from app.api.error_mapping import map_app_error
from app.core.config import settings
from app.domain.errors import AppError, ValidationError
from app.infrastructure.db.models import Category, Document, DocumentCategory, DocumentStatus, DocumentStatusAssignment
from app.infrastructure.db.models import DocumentEntity, DocumentTag, Entity, EntityType, PredictionSource, Source, Tag, User
from app.infrastructure.db.models import DocumentType
from app.infrastructure.db.session import AsyncSessionLocal, get_db
from app.schemas.documents import (
    DocumentCategoryCatalogItem,
    DocumentCategorizeItem,
    DocumentCategorizeResponse,
    DocumentCategoryAssignRequest,
    DocumentEntityAssignRequest,
    DocumentEntityItem,
    DocumentListEntityItem,
    DocumentListItem,
    DocumentListResponse,
    DocumentListTagItem,
    DocumentStatusCatalogItem,
    DocumentExtractResponse,
    DocumentEntitiesExtractResponse,
    DocumentMetadataUpdateRequest,
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
    DocumentTypeCatalogItem,
    DocumentTranslateRequest,
    DocumentTranslateTitleResponse,
    DocumentUpdateRequest,
    ExtractUrlPersistRequest,
    CreateDocumentRawRequest,
    SummarySource,
)
from app.services.documents.db_refs import entity_type_id_by_code, language_id_by_code, prediction_source_id
from app.services.documents.document_embedding import EmbeddingStage, embed_document_stages_best_effort
from app.services.documents.document_pipeline import (
    acquire_edit_lock,
    create_document_after_extract,
    create_document_from_raw_text,
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
    run_translate_document_title,
    save_document_after_edit,
    sync_document_statuses,
    update_document_metadata,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.llm.summarizer import refine_summary, summarize_text
from app.services.llm.translator import detect_language, translate_text
from app.api.document_streaming import stream_manual_api_llm
from app.services.processing.document_api_jobs import (
    manual_summary_refine_spec,
    manual_summary_spec,
    manual_translate_spec,
)
from app.services.parsing.extractor import download_html, extract_article_text
router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

DOCUMENT_ENTITY_TYPE_CODES = frozenset({"military_equipment", "manufacturer", "contract"})
TAG_LANGUAGE_SCOPES = frozenset({"original", "translated"})


async def _prepare_write_session(db: AsyncSession) -> None:
    """Depends() уже мог выполнить SELECT — сессия в autobegin; иначе db.begin() даст InvalidRequestError."""
    await db.rollback()


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


async def _get_document_categories(
    db: AsyncSession,
    document_id: UUID,
) -> list[DocumentCategorizeItem]:
    parent = aliased(Category)
    rows = await db.execute(
        select(
            Category.id,
            Category.code,
            Category.name,
            Category.name_ru,
            Category.level,
            parent.id.label("parent_id"),
            parent.code.label("parent_code"),
            parent.name.label("parent_name"),
            parent.name_ru.label("parent_name_ru"),
            DocumentCategory.confidence,
            PredictionSource.code.label("prediction_source_code"),
        )
        .select_from(DocumentCategory)
        .join(Category, Category.id == DocumentCategory.category_id)
        .outerjoin(parent, parent.id == Category.parent_id)
        .outerjoin(PredictionSource, PredictionSource.id == DocumentCategory.prediction_source_id)
        .where(
            DocumentCategory.document_id == document_id,
            Category.level.in_((1, 2, 3)),
        )
        .order_by(Category.sort_order.asc(), Category.code.asc())
    )
    out: list[DocumentCategorizeItem] = []
    for row in rows:
        cid, code, name, name_ru, level, parent_id, parent_code, parent_name, parent_name_ru, conf, ps_code = row
        conf_f = float(conf) if conf is not None else 1.0
        conf_f = max(0.0, min(1.0, conf_f))
        out.append(
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
                confidence=conf_f,
                prediction_source_code=ps_code or "unknown",
                text_source=None,
            )
        )
    return out


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    status_code: Annotated[list[str] | None, Query()] = None,
    document_id: UUID | None = Query(default=None, description="Один документ по id (как в списке)"),
    document_type_code: str | None = Query(default=None, min_length=1, max_length=64),
    source_id: UUID | None = Query(default=None, description="Фильтр по источнику (RSS/URL); только свои источники"),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    use_published_date: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    normalized_statuses: list[str] = []
    if status_code:
        for raw in status_code:
            if not raw:
                continue
            t = raw.strip().lower()
            if not t:
                continue
            if len(t) > 64:
                raise HTTPException(status_code=400, detail="Код статуса не должен быть длиннее 64 символов")
            normalized_statuses.append(t)
        normalized_statuses = list(dict.fromkeys(normalized_statuses))
    normalized_type = document_type_code.strip().lower() if document_type_code else None
    date_field = Document.published_at if use_published_date else Document.created_at

    stmt = (
        select(
            Document.id,
            Document.title,
            Document.translated_title,
            Document.source_url,
            Document.original_language_id,
            Document.translated_language_id,
            Document.original_content,
            Document.translated_content,
            Document.created_at,
            Document.published_at,
            Document.extracted_main_image,
            Document.original_summary,
            Document.translated_summary,
            DocumentType.code.label("document_type_code"),
            DocumentType.name.label("document_type_name"),
        )
        .join(DocumentType, DocumentType.id == Document.document_type_id)
    )

    filters = []
    if source_id is not None:
        src = await db.get(Source, source_id)
        if src is None:
            raise HTTPException(status_code=404, detail="Источник не найден")
        if not user.is_admin and src.user_id != user.id:
            raise HTTPException(status_code=403, detail="Нет доступа к источнику")
        filters.append(Document.source_id == source_id)
    if document_id is not None:
        filters.append(Document.id == document_id)
    if normalized_type:
        filters.append(DocumentType.code == normalized_type)
    if date_from:
        filters.append(date_field >= date_from)
    if date_to:
        filters.append(date_field <= date_to)
    if normalized_statuses:
        exists_by_code = [
            select(DocumentStatusAssignment.document_id)
            .join(DocumentStatus, DocumentStatus.id == DocumentStatusAssignment.status_id)
            .where(
                DocumentStatusAssignment.document_id == Document.id,
                DocumentStatus.code == code,
            )
            .exists()
            for code in normalized_statuses
        ]
        filters.append(or_(*exists_by_code))
    if filters:
        stmt = stmt.where(and_(*filters))

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await db.execute(stmt.order_by(Document.created_at.desc()).offset(offset).limit(limit))
    docs = list(rows)
    if not docs:
        return DocumentListResponse(total=total or 0, items=[])

    doc_ids = [row.id for row in docs]

    status_rows = await db.execute(
        select(
            DocumentStatusAssignment.document_id,
            DocumentStatus.code,
            DocumentStatus.name_ru,
            DocumentStatus.description,
            DocumentStatusAssignment.assigned_at,
            DocumentStatusAssignment.assigned_by_id,
        )
        .join(DocumentStatus, DocumentStatus.id == DocumentStatusAssignment.status_id)
        .where(DocumentStatusAssignment.document_id.in_(doc_ids))
        .order_by(DocumentStatusAssignment.assigned_at.desc(), DocumentStatus.code.asc())
    )
    statuses_map: dict[UUID, list[DocumentStatusItem]] = {}
    for row in status_rows:
        statuses_map.setdefault(row.document_id, []).append(
            DocumentStatusItem(
                code=row.code,
                name_ru=row.name_ru,
                description=row.description,
                assigned_at=row.assigned_at,
                assigned_by_id=row.assigned_by_id,
            )
        )

    category_ids = set(
        await db.scalars(select(DocumentCategory.document_id).where(DocumentCategory.document_id.in_(doc_ids)))
    )
    entity_ids = set(await db.scalars(select(DocumentEntity.document_id).where(DocumentEntity.document_id.in_(doc_ids))))
    tag_ids = set(await db.scalars(select(DocumentTag.document_id).where(DocumentTag.document_id.in_(doc_ids))))

    parent = aliased(Category)
    category_rows = await db.execute(
        select(
            DocumentCategory.document_id,
            Category.id,
            Category.code,
            Category.name,
            Category.name_ru,
            Category.level,
            parent.id.label("parent_id"),
            parent.code.label("parent_code"),
            parent.name.label("parent_name"),
            parent.name_ru.label("parent_name_ru"),
            DocumentCategory.confidence,
            PredictionSource.code.label("prediction_source_code"),
        )
        .join(Category, Category.id == DocumentCategory.category_id)
        .outerjoin(parent, parent.id == Category.parent_id)
        .outerjoin(PredictionSource, PredictionSource.id == DocumentCategory.prediction_source_id)
        .where(
            DocumentCategory.document_id.in_(doc_ids),
            Category.level.in_((1, 2, 3)),
        )
        .order_by(Category.sort_order.asc(), Category.code.asc())
    )
    categories_map: dict[UUID, list[DocumentCategorizeItem]] = {}
    for row in category_rows:
        conf_f = float(row.confidence) if row.confidence is not None else 1.0
        conf_f = max(0.0, min(1.0, conf_f))
        categories_map.setdefault(row.document_id, []).append(
            DocumentCategorizeItem(
                category_id=row.id,
                code=row.code,
                name=row.name,
                name_ru=row.name_ru,
                level=row.level,
                parent_id=row.parent_id,
                parent_code=row.parent_code,
                parent_name=row.parent_name,
                parent_name_ru=row.parent_name_ru,
                confidence=conf_f,
                prediction_source_code=row.prediction_source_code or "unknown",
                text_source=None,
            )
        )

    entity_rows = await db.execute(
        select(DocumentEntity.document_id, Entity.id, Entity.name, EntityType.code)
        .join(Entity, Entity.id == DocumentEntity.entity_id)
        .join(EntityType, EntityType.id == Entity.entity_type_id)
        .where(DocumentEntity.document_id.in_(doc_ids))
        .order_by(Entity.name.asc())
    )
    entities_map: dict[UUID, list[DocumentListEntityItem]] = {}
    for row in entity_rows:
        name = (row.name or "").strip()
        if name:
            entities_map.setdefault(row.document_id, []).append(
                DocumentListEntityItem(
                    id=row.id,
                    name=name,
                    entity_type_code=row.code,
                )
            )

    tag_rows = await db.execute(
        select(DocumentTag.document_id, Tag.id, Tag.name, Tag.language_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(doc_ids))
        .order_by(Tag.name.asc())
    )
    doc_languages = {
        row.id: (row.original_language_id, row.translated_language_id)
        for row in docs
    }
    original_tags_map: dict[UUID, list[DocumentListTagItem]] = {}
    translated_tags_map: dict[UUID, list[DocumentListTagItem]] = {}
    for row in tag_rows:
        name = (row.name or "").strip()
        if name:
            item = DocumentListTagItem(id=row.id, name=name)
            original_lang_id, translated_lang_id = doc_languages.get(row.document_id, (None, None))
            if original_lang_id is not None and row.language_id == original_lang_id:
                original_tags_map.setdefault(row.document_id, []).append(item)
            elif translated_lang_id is not None and row.language_id == translated_lang_id:
                translated_tags_map.setdefault(row.document_id, []).append(item)
            else:
                original_tags_map.setdefault(row.document_id, []).append(item)

    items = [
        DocumentListItem(
            document_id=row.id,
            title=row.title,
            translated_title=row.translated_title,
            source_url=row.source_url,
            document_type_code=row.document_type_code,
            document_type_name=row.document_type_name,
            created_at=row.created_at,
            published_at=row.published_at,
            annotation=(row.translated_summary or row.original_summary),
            main_image=row.extracted_main_image,
            statuses=statuses_map.get(row.id, []),
            has_translation=bool((row.translated_content or "").strip()),
            has_annotation=bool((row.translated_summary or row.original_summary or "").strip()),
            has_translated_summary=bool((row.translated_summary or "").strip()),
            has_original_content=bool((row.original_content or "").strip()),
            has_categories=row.id in category_ids,
            has_entities=row.id in entity_ids,
            has_tags=row.id in tag_ids,
            categories=categories_map.get(row.id, []),
            entities=entities_map.get(row.id, []),
            original_tags=original_tags_map.get(row.id, []),
            translated_tags=translated_tags_map.get(row.id, []),
        )
        for row in docs
    ]
    return DocumentListResponse(total=total or 0, items=items)


@router.delete("/{document_id}")
async def delete_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Удаление документа (CASCADE по связям документа).

    Теги и сущности из справочников ``tags`` / ``entities`` удаляются только если после
    удаления документа на них больше нет ни одной строки в ``document_tags`` / ``document_entities``.
    Доступ: владелец документа или администратор.
    """
    user_id = user.id
    user_is_admin = user.is_admin
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not user_is_admin and doc.created_by_id != user_id:
        raise HTTPException(status_code=403, detail="Нет права удалить этот документ")

    tag_ids = list(
        dict.fromkeys(
            (await db.scalars(select(DocumentTag.tag_id).where(DocumentTag.document_id == document_id))).all(),
        ),
    )
    entity_ids = list(
        dict.fromkeys(
            (await db.scalars(select(DocumentEntity.entity_id).where(DocumentEntity.document_id == document_id))).all(),
        ),
    )

    await _prepare_write_session(db)
    async with db.begin():
        await db.execute(delete(Document).where(Document.id == document_id))
        if tag_ids:
            still_linked = exists(select(1).where(DocumentTag.tag_id == Tag.id))
            await db.execute(delete(Tag).where(Tag.id.in_(tag_ids), ~still_linked))
        if entity_ids:
            still_linked_ent = exists(select(1).where(DocumentEntity.entity_id == Entity.id))
            await db.execute(delete(Entity).where(Entity.id.in_(entity_ids), ~still_linked_ent))

    return {"ok": True, "document_id": str(document_id)}


@router.get("/{document_id}/editor", response_model=DocumentExtractResponse)
async def get_document_editor_snapshot(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Снимок документа для экрана редактирования (как после extract-url)."""
    user_id = user.id
    user_is_admin = user.is_admin
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    if not user_is_admin and doc.created_by_id != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к документу")

    statuses = await _get_document_status_items(db, document_id)
    original_tags, translated_tags = await _get_document_tags(db, doc)
    entities_military_equipment, entities_manufacturers, entities_contracts = await _get_document_entities(
        db, document_id
    )
    categories = await _get_document_categories(db, document_id)
    return document_to_extract_response(
        doc,
        from_cache=True,
        statuses=statuses,
        original_tags=original_tags,
        translated_tags=translated_tags,
        entities_military_equipment=entities_military_equipment,
        entities_manufacturers=entities_manufacturers,
        entities_contracts=entities_contracts,
        categories=categories,
    )


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
        categories = await _get_document_categories(db, existing.id)
        return document_to_extract_response(
            existing,
            from_cache=True,
            statuses=statuses,
            original_tags=original_tags,
            translated_tags=translated_tags,
            entities_military_equipment=entities_military_equipment,
            entities_manufacturers=entities_manufacturers,
            entities_contracts=entities_contracts,
            categories=categories,
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
        await embed_document_stages_best_effort(doc_id, EmbeddingStage.ORIGINAL)
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
            categories = await _get_document_categories(db, existing2.id)
            return document_to_extract_response(
                existing2,
                from_cache=True,
                statuses=statuses,
                original_tags=original_tags,
                translated_tags=translated_tags,
                entities_military_equipment=entities_military_equipment,
                entities_manufacturers=entities_manufacturers,
                entities_contracts=entities_contracts,
                categories=categories,
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
        categories=[],
    )


@router.post("/from-raw", response_model=DocumentExtractResponse)
async def create_document_from_raw(
    payload: CreateDocumentRawRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Создать документ из сырого текста: статусы new + unprocessed, как после извлечения по URL."""
    created_by_id = user.id if user else None
    await _prepare_write_session(db)
    try:
        async with db.begin():
            doc = await create_document_from_raw_text(
                db,
                title=payload.title,
                author=payload.author,
                publication_date=payload.publication_date,
                text=payload.text,
                created_by_id=created_by_id,
                document_type_code=payload.document_type_code,
                source_url=normalize_source_url(str(payload.source_url)) if payload.source_url else None,
                main_image=str(payload.main_image).strip()[:8192] if payload.main_image else None,
            )
            translated_body = (payload.translated_content or "").strip()
            if translated_body:
                doc.translated_content = translated_body
                doc.translated_language_id = await language_id_by_code(db, payload.target_lang)
                doc.translated_summary_stale = True
            doc_id = doc.id
        embed_stages = [EmbeddingStage.ORIGINAL]
        if (payload.translated_content or "").strip():
            embed_stages.append(EmbeddingStage.TRANSLATED)
        await embed_document_stages_best_effort(doc_id, *embed_stages)
    except ValidationError as exc:
        await db.rollback()
        _handle(exc)

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
        categories=[],
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


@router.get("/types/catalog", response_model=list[DocumentTypeCatalogItem])
async def document_types_catalog(
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(DocumentType.code, DocumentType.name, DocumentType.description).order_by(DocumentType.name.asc())
    )
    return [
        DocumentTypeCatalogItem(
            code=row.code,
            name=row.name,
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
        )
    return {"ok": True, "document_id": str(document_id), "status_code": status_code}


@router.delete("/{document_id}/statuses/{status_code}")
async def remove_document_status(
    document_id: UUID,
    status_code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
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

    spec = manual_translate_spec(document_id, started_by_id, stream=True)

    async def persist_translation(translated_text: str) -> None:
        async with AsyncSessionLocal() as w_session:
            async with w_session.begin():
                await persist_document_translation(
                    w_session,
                    document_id=document_id,
                    translated_text=translated_text,
                    target_lang=target_lang,
                    started_by_id=started_by_id,
                    track_job=False,
                )

    async def body():
        async for chunk in stream_manual_api_llm(
            spec,
            llm_stream_factory=lambda: translate_text(
                source_text, target_lang=target_lang, stream=True
            ),
            persist=persist_translation,
        ):
            yield chunk

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


@router.post("/{document_id}/translate-title", response_model=DocumentTranslateTitleResponse)
async def document_translate_title(
    document_id: UUID,
    payload: DocumentTranslateRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    """Перевод заголовка документа (синхронно, без очереди). Короткая операция — как POST /translate без стрима."""
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            doc = await run_translate_document_title(
                db,
                document_id=document_id,
                target_lang=payload.target_lang,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return DocumentTranslateTitleResponse(
        document_id=document_id,
        translated_title=(doc.translated_title or "").strip(),
    )


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
    user_id = user.id
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
        )
    return {"ok": True, "document_id": str(document_id), "tag_id": str(payload.tag_id)}


@router.delete("/{document_id}/tags/{tag_id}")
async def remove_document_tag(
    document_id: UUID,
    tag_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
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
    user_id = user.id
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
        )
    return {"ok": True, "document_id": str(document_id), "entity_id": str(payload.entity_id)}


@router.delete("/{document_id}/entities/{entity_id}")
async def remove_document_entity(
    document_id: UUID,
    entity_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
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
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
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


@router.get("/{document_id}/categories", response_model=DocumentCategorizeResponse)
async def get_document_categories_snapshot(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    categories = await _get_document_categories(db, document_id)
    return DocumentCategorizeResponse(document_id=document_id, categories=categories)


@router.get("/{document_id}/categories/catalog", response_model=list[DocumentCategoryCatalogItem])
async def document_categories_catalog(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    assigned_rows = await db.execute(
        select(DocumentCategory.category_id).where(DocumentCategory.document_id == document_id)
    )
    assigned_ids = {row[0] for row in assigned_rows}

    parent = aliased(Category)
    stmt = (
        select(
            Category.id,
            Category.code,
            Category.name,
            Category.name_ru,
            Category.level,
            parent.id.label("parent_id"),
            parent.code.label("parent_code"),
            parent.name.label("parent_name"),
            parent.name_ru.label("parent_name_ru"),
        )
        .where(
            Category.is_active.is_(True),
            Category.level.in_((1, 2, 3)),
        )
        .outerjoin(parent, parent.id == Category.parent_id)
        .order_by(Category.sort_order.asc(), Category.code.asc())
    )
    if assigned_ids:
        stmt = stmt.where(Category.id.not_in(assigned_ids))

    rows = await db.execute(stmt)
    return [
        DocumentCategoryCatalogItem(
            category_id=row.id,
            code=row.code,
            name=row.name,
            name_ru=row.name_ru,
            level=row.level,
            parent_id=row.parent_id,
            parent_code=row.parent_code,
            parent_name=row.parent_name,
            parent_name_ru=row.parent_name_ru,
        )
        for row in rows
    ]


@router.post("/{document_id}/categories/assign")
async def assign_document_category(
    document_id: UUID,
    payload: DocumentCategoryAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    cat = await db.get(Category, payload.category_id)
    if cat is None or not cat.is_active:
        raise HTTPException(status_code=404, detail="Категория не найдена")
    if cat.level not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Назначение категорий этого уровня запрещено")

    manual_id = await prediction_source_id(db, "manual")
    await _prepare_write_session(db)
    async with db.begin():
        stmt = insert(DocumentCategory).values(
            document_id=document_id,
            category_id=payload.category_id,
            confidence=Decimal("1"),
            prediction_source_id=manual_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[DocumentCategory.document_id, DocumentCategory.category_id],
            set_={
                "confidence": stmt.excluded.confidence,
                "prediction_source_id": stmt.excluded.prediction_source_id,
            },
        )
        await db.execute(stmt)
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
        )
    return {"ok": True, "document_id": str(document_id), "category_id": str(payload.category_id)}


@router.delete("/{document_id}/categories/{category_id}")
async def remove_document_category(
    document_id: UUID,
    category_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    user_id = user.id
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

    await _prepare_write_session(db)
    async with db.begin():
        await db.execute(
            delete(DocumentCategory).where(
                DocumentCategory.document_id == document_id,
                DocumentCategory.category_id == category_id,
            )
        )
        await sync_document_statuses(
            db,
            document_id=document_id,
            assigned_by_id=user_id,
        )
    return {"ok": True, "document_id": str(document_id), "category_id": str(category_id)}


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

    spec = manual_summary_refine_spec(document_id, started_by_id, stream=True)

    async def persist_refined(refined_annotation: str) -> None:
        async with AsyncSessionLocal() as w_session:
            async with w_session.begin():
                await persist_document_refined_summary(
                    w_session,
                    document_id=document_id,
                    source=source,
                    refined_annotation=refined_annotation,
                    started_by_id=started_by_id,
                    track_job=False,
                )

    async def body():
        async for chunk in stream_manual_api_llm(
            spec,
            llm_stream_factory=lambda: refine_summary(
                article_text=article,
                summary=summary,
                user_instruction=user_instruction,
                mode=mode,
                stream=True,
            ),
            persist=persist_refined,
        ):
            yield chunk

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

    spec = manual_summary_spec(document_id, started_by_id, stream=True)

    async def persist_summary(annotation: str) -> None:
        async with AsyncSessionLocal() as w_session:
            async with w_session.begin():
                await persist_document_summary(
                    w_session,
                    document_id=document_id,
                    source=source,
                    annotation=annotation,
                    started_by_id=started_by_id,
                    track_job=False,
                )

    async def body():
        async for chunk in stream_manual_api_llm(
            spec,
            llm_stream_factory=lambda: summarize_text(source_text, stream=True),
            persist=persist_summary,
        ):
            yield chunk

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


@router.patch("/{document_id}/metadata")
async def document_update_metadata(
    document_id: UUID,
    payload: DocumentMetadataUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ = user
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await update_document_metadata(
                db,
                document_id=document_id,
                body=payload,
            )
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}
