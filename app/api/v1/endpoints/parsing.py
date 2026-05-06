from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.error_mapping import map_app_error
from app.domain.errors import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.infrastructure.db.models import (
    Country,
    Document,
    DocumentStatus,
    DocumentStatusAssignment,
    DocumentType,
    Language,
    Source,
    User,
)
from app.infrastructure.db.session import get_db
from app.schemas.parsing import (
    CountryCatalogItem,
    LanguageCatalogItem,
    ParseSourceDocumentItem,
    ParseSourceRequest,
    ParseSourceResponse,
    SourceCreateRequest,
    SourceCreateResponse,
    SourceListItem,
    SourceListResponse,
)
from app.services.documents.db_refs import document_type_id_by_code
from app.services.documents.document_pipeline import (
    _published_at_from_extract_date,
    create_document_after_extract,
    get_document_by_source_url,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.parsing.source_discovery import DiscoveredUrl, discover_source_news_urls

router = APIRouter(prefix="/parsing", tags=["parsing"])
PARSE_SOURCE_MAX_CONCURRENCY = 3
PARSE_SOURCE_REQUEST_DELAY_SEC = 0.35


def _published_at_from_parse_extract(extract_payload: dict) -> datetime | None:
    raw_date = extract_payload.get("date")
    extracted_date: str | None = None
    if raw_date is not None:
        ds = str(raw_date).strip()
        if ds:
            extracted_date = ds[:128]
    return _published_at_from_extract_date(extracted_date)


def _final_published_at_for_parse(item: DiscoveredUrl, extract_payload: dict) -> datetime | None:
    if item.published_at is not None:
        pub = item.published_at
        return pub if pub.tzinfo else pub.replace(tzinfo=UTC)
    return _published_at_from_parse_extract(extract_payload)


def _published_at_within_depth(final_published_at: datetime, *, threshold_utc: datetime) -> bool:
    pub = final_published_at if final_published_at.tzinfo else final_published_at.replace(tzinfo=UTC)
    pub = pub.astimezone(UTC)
    return pub >= threshold_utc


async def _prepare_write_session(db: AsyncSession) -> None:
    await db.rollback()


async def _language_id_by_code(db: AsyncSession, code: str) -> UUID:
    lang_id = await db.scalar(select(Language.id).where(Language.code == code.lower()))
    if lang_id is None:
        lang_id = await db.scalar(select(Language.id).where(Language.code == "en"))
    if lang_id is None:
        raise HTTPException(status_code=500, detail="Язык по умолчанию en не найден")
    return lang_id


async def _country_id_by_code(db: AsyncSession, code: str | None) -> UUID | None:
    if not code:
        return None
    return await db.scalar(select(Country.id).where(Country.code == code.upper()))


@router.get("/languages/catalog", response_model=list[LanguageCatalogItem])
async def list_languages_catalog(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Language).order_by(Language.name.asc()))
    languages = result.scalars().all()
    return [LanguageCatalogItem.model_validate(lang) for lang in languages]


@router.get("/countries/catalog", response_model=list[CountryCatalogItem])
async def list_countries_catalog(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    result = await db.execute(select(Country).order_by(Country.name.asc()))
    countries = result.scalars().all()
    return [CountryCatalogItem.model_validate(c) for c in countries]


async def _list_unprocessed_by_source(
    db: AsyncSession,
    *,
    source_id: UUID,
    document_ids: set[UUID] | None = None,
) -> list[ParseSourceDocumentItem]:
    q = (
        select(Document)
        .join(DocumentStatusAssignment, DocumentStatusAssignment.document_id == Document.id)
        .join(DocumentStatus, DocumentStatus.id == DocumentStatusAssignment.status_id)
        .where(Document.source_id == source_id, DocumentStatus.code == "unprocessed")
        .order_by(Document.created_at.desc())
    )
    if document_ids is not None:
        if not document_ids:
            return []
        q = q.where(Document.id.in_(document_ids))
    rows = await db.execute(q)
    items = rows.scalars().all()
    return [
        ParseSourceDocumentItem(
            document_id=item.id,
            title=item.title,
            source_url=item.source_url,
            published_at=item.published_at,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.get("/sources", response_model=SourceListResponse)
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    added_by_user_id: UUID | None = Query(
        default=None,
        description="Только для администратора: фильтр по пользователю, добавившему источник",
    ),
):
    documents_total_sq = (
        select(func.count())
        .select_from(Document)
        .where(Document.source_id == Source.id)
        .scalar_subquery()
    )
    documents_unprocessed_sq = (
        select(func.count())
        .select_from(Document)
        .join(DocumentStatusAssignment, DocumentStatusAssignment.document_id == Document.id)
        .join(DocumentStatus, DocumentStatus.id == DocumentStatusAssignment.status_id)
        .where(Document.source_id == Source.id, DocumentStatus.code == "unprocessed")
        .scalar_subquery()
    )
    stmt = (
        select(
            Source,
            User.username,
            Language.code,
            Country.code,
            DocumentType.code,
            DocumentType.name,
            documents_total_sq,
            documents_unprocessed_sq,
        )
        .join(User, User.id == Source.user_id)
        .join(Language, Language.id == Source.language_id)
        .join(DocumentType, DocumentType.id == Source.document_type_id)
        .outerjoin(Country, Country.id == Source.country_id)
    )
    if user.is_admin:
        if added_by_user_id is not None:
            stmt = stmt.where(Source.user_id == added_by_user_id)
    else:
        stmt = stmt.where(Source.user_id == user.id)

    stmt = stmt.order_by(Source.created_at.desc())
    result = await db.execute(stmt)
    rows = result.all()
    items = [
        SourceListItem(
            source_id=src.id,
            name=src.name,
            url=src.url,
            rss_url=src.rss_url,
            language_code=lang_code or "en",
            country_code=c_code,
            document_type_code=dt_code,
            document_type_name=dt_name,
            is_active=src.is_active,
            created_at=src.created_at,
            added_by_user_id=src.user_id,
            added_by_username=username,
            documents_total=int(docs_total or 0),
            documents_unprocessed=int(docs_unprocessed or 0),
            last_parse_created_total=src.last_parse_created_total,
            last_parse_at=src.last_parse_at,
        )
        for src, username, lang_code, c_code, dt_code, dt_name, docs_total, docs_unprocessed in rows
    ]
    return SourceListResponse(
        total=len(items),
        items=items,
        can_filter_by_all_users=user.is_admin,
    )


async def _extract_single_article_for_parse_source(
    url: str,
    *,
    delay_sec: float,
    download_html_func,
    extract_article_text_func,
) -> dict[str, Any] | None:
    await asyncio.sleep(delay_sec)
    try:
        html = await download_html_func(url)
        return await extract_article_text_func(html, url)
    except HTTPException:
        return None


@router.post("/sources", response_model=SourceCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: SourceCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    language_id = await _language_id_by_code(db, payload.language_code)
    country_id = await _country_id_by_code(db, payload.country_code)
    try:
        dt_id = await document_type_id_by_code(db, payload.document_type_code.strip().lower())
    except NoResultFound as exc:
        raise HTTPException(status_code=400, detail="Неизвестный код типа документа") from exc

    source = Source(
        user_id=user.id,
        document_type_id=dt_id,
        name=(payload.name.strip() if payload.name else None),
        url=normalize_source_url(str(payload.url)),
        country_id=country_id,
        language_id=language_id,
        rss_url=(normalize_source_url(str(payload.rss_url)) if payload.rss_url else None),
        is_active=True,
    )
    db.add(source)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Источник с таким URL уже существует для текущего пользователя",
        ) from None
    await db.refresh(source)

    lang_code = await db.scalar(select(Language.code).where(Language.id == source.language_id))
    c_code = await db.scalar(select(Country.code).where(Country.id == source.country_id)) if source.country_id else None
    dt_row = (
        await db.execute(
            select(DocumentType.code, DocumentType.name).where(DocumentType.id == source.document_type_id),
        )
    ).one()
    dt_code, dt_name = dt_row[0], dt_row[1]
    return SourceCreateResponse(
        source_id=source.id,
        url=source.url,
        name=source.name,
        language_code=lang_code or "en",
        country_code=c_code,
        rss_url=source.rss_url,
        is_active=source.is_active,
        document_type_code=dt_code,
        document_type_name=dt_name,
    )


@router.delete("/sources/{source_id}")
async def deactivate_source(
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    source = await db.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if source.user_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к источнику")

    if source.is_active:
        source.is_active = False
        await db.commit()

    return {"ok": True, "source_id": str(source_id), "is_active": source.is_active}


@router.post("/sources/parse", response_model=ParseSourceResponse)
async def parse_source(
    payload: ParseSourceRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    from app.services.parsing.extractor import download_html, extract_article_text

    source = await db.get(Source, payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if not source.is_active:
        raise HTTPException(status_code=400, detail="Источник неактивен")
    source_id = source.id

    doc_type_row = (
        await db.execute(select(DocumentType.code).where(DocumentType.id == source.document_type_id))
    ).one_or_none()
    if doc_type_row is None:
        raise HTTPException(status_code=500, detail="У источника не задан тип документа")
    document_type_code = doc_type_row[0]

    discovered = await discover_source_news_urls(
        source.url,
        rss_url=source.rss_url,
        days=payload.days,
        skip_undated=payload.skip_undated,
    )
    depth_threshold_utc = datetime.now(UTC) - timedelta(days=payload.days)
    created_by_id = user.id if user else None

    new_doc_ids: set[UUID] = set()
    candidates = []
    for item in discovered:
        existing = await get_document_by_source_url(db, item.url)
        if existing is None:
            candidates.append(item)

    sem = asyncio.Semaphore(PARSE_SOURCE_MAX_CONCURRENCY)

    async def _bounded_extract(item, idx: int):
        async with sem:
            delay = (idx % PARSE_SOURCE_MAX_CONCURRENCY) * PARSE_SOURCE_REQUEST_DELAY_SEC
            extracted = await _extract_single_article_for_parse_source(
                item.url,
                delay_sec=delay,
                download_html_func=download_html,
                extract_article_text_func=extract_article_text,
            )
            return item, extracted

    extracted_results = await asyncio.gather(
        *[_bounded_extract(item, idx) for idx, item in enumerate(candidates)],
    )

    for item, extracted in extracted_results:
        if extracted is None:
            continue

        final_pub = _final_published_at_for_parse(item, extracted)
        if payload.skip_undated and final_pub is None:
            continue
        if final_pub is not None and not _published_at_within_depth(
            final_pub,
            threshold_utc=depth_threshold_utc,
        ):
            continue

        await _prepare_write_session(db)
        try:
            async with db.begin():
                doc = await create_document_after_extract(
                    db,
                    norm_url=normalize_source_url(item.url),
                    extract_payload=extracted,
                    created_by_id=created_by_id,
                    document_type_code=document_type_code,
                )
                doc.source_id = source_id
                if item.published_at is not None:
                    doc.published_at = item.published_at

                new_doc_ids.add(doc.id)
        except ValidationError as exc:
            await db.rollback()
            raise map_app_error(exc) from exc
        except IntegrityError:
            await db.rollback()
            continue

    existing_unprocessed = await _list_unprocessed_by_source(db, source_id=source_id)
    new_unprocessed = await _list_unprocessed_by_source(
        db,
        source_id=source_id,
        document_ids=new_doc_ids,
    )
    await db.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(
            last_parse_at=datetime.now(UTC),
            last_parse_created_total=len(new_doc_ids),
        ),
    )
    await db.commit()
    return ParseSourceResponse(
        source_id=source_id,
        found_total=len(discovered),
        created_total=len(new_doc_ids),
        existing_unprocessed_by_source=existing_unprocessed,
        new_unprocessed_by_source=new_unprocessed,
    )
