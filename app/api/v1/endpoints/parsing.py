from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.infrastructure.db.models import (
    Country,
    Document,
    DocumentStatus,
    DocumentStatusAssignment,
    Language,
    Source,
    User,
)
from app.infrastructure.db.session import get_db
from app.schemas.parsing import (
    ParseSourceDocumentItem,
    ParseSourceRequest,
    ParseSourceResponse,
    SourceCreateRequest,
    SourceCreateResponse,
)
from app.services.documents.document_pipeline import (
    create_document_after_extract,
    get_document_by_source_url,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.parsing.source_discovery import discover_source_news_urls

router = APIRouter(prefix="/parsing", tags=["parsing"])
PARSE_SOURCE_MAX_CONCURRENCY = 3
PARSE_SOURCE_REQUEST_DELAY_SEC = 0.35


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


async def _status_ids_by_codes(db: AsyncSession, *codes: str) -> dict[str, UUID]:
    rows = await db.execute(select(DocumentStatus.code, DocumentStatus.id).where(DocumentStatus.code.in_(codes)))
    out = {code: sid for code, sid in rows}
    missing = [code for code in codes if code not in out]
    if missing:
        raise HTTPException(status_code=500, detail=f"Не найдены коды статусов: {', '.join(missing)}")
    return out


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

    source = Source(
        user_id=user.id,
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
    return SourceCreateResponse(
        source_id=source.id,
        url=source.url,
        name=source.name,
        language_code=lang_code or "en",
        country_code=c_code,
        rss_url=source.rss_url,
        is_active=source.is_active,
    )


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

    status_ids = await _status_ids_by_codes(db, "new", "unprocessed")
    discovered = await discover_source_news_urls(source.url, rss_url=source.rss_url, days=payload.days)
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

        await _prepare_write_session(db)
        try:
            async with db.begin():
                doc = await create_document_after_extract(
                    db,
                    norm_url=normalize_source_url(item.url),
                    extract_payload=extracted,
                    created_by_id=created_by_id,
                    document_type_code=payload.document_type_code,
                )
                doc.source_id = source.id
                doc.published_at = item.published_at

                await db.execute(
                    insert(DocumentStatusAssignment)
                    .values(
                        [
                            {
                                "document_id": doc.id,
                                "status_id": status_ids["new"],
                                "assigned_by_id": created_by_id,
                            },
                            {
                                "document_id": doc.id,
                                "status_id": status_ids["unprocessed"],
                                "assigned_by_id": created_by_id,
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
                new_doc_ids.add(doc.id)
        except IntegrityError:
            await db.rollback()
            continue

    existing_unprocessed = await _list_unprocessed_by_source(db, source_id=source.id)
    new_unprocessed = await _list_unprocessed_by_source(
        db,
        source_id=source.id,
        document_ids=new_doc_ids,
    )
    return ParseSourceResponse(
        source_id=source.id,
        found_total=len(discovered),
        created_total=len(new_doc_ids),
        existing_unprocessed_by_source=existing_unprocessed,
        new_unprocessed_by_source=new_unprocessed,
    )
