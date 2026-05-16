"""Разбор источника (discovery + extract + создание документов) для API и SAQ-воркера."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ValidationError
from app.infrastructure.db.models import (
    Document,
    DocumentStatus,
    DocumentStatusAssignment,
    DocumentType,
    Source,
    SourceParseRun,
)
from app.schemas.parsing import ParseSourceDocumentItem
from app.services.documents.document_embedding import EmbeddingStage, embed_document_if_stale
from app.services.documents.document_pipeline import (
    _published_at_from_extract_date,
    create_document_after_extract,
    get_document_by_source_url,
)
from app.services.documents.url_norm import normalize_source_url
from app.services.parsing.source_discovery import DiscoveredUrl, discover_source_news_urls

PARSE_SOURCE_MAX_CONCURRENCY = 3
PARSE_SOURCE_REQUEST_DELAY_SEC = 0.35


async def bump_parse_run_progress(
    db: AsyncSession,
    parse_run_id: UUID | None,
    *,
    phase: str,
    found_total: int | None = None,
) -> None:
    """Коммитит фазу для SSE/мониторинга (отдельные короткие транзакции)."""
    if parse_run_id is None:
        return
    values: dict[str, Any] = {"phase": phase}
    if found_total is not None:
        values["found_total"] = found_total
    await db.execute(update(SourceParseRun).where(SourceParseRun.id == parse_run_id).values(**values))
    await db.commit()


@dataclass(frozen=True, slots=True)
class ParseSourceWorkOutcome:
    found_total: int
    created_total: int
    new_document_ids: set[UUID]


def published_at_from_parse_extract(extract_payload: dict) -> datetime | None:
    raw_date = extract_payload.get("date")
    extracted_date: str | None = None
    if raw_date is not None:
        ds = str(raw_date).strip()
        if ds:
            extracted_date = ds[:128]
    return _published_at_from_extract_date(extracted_date)


def final_published_at_for_parse(item: DiscoveredUrl, extract_payload: dict) -> datetime | None:
    if item.published_at is not None:
        pub = item.published_at
        return pub if pub.tzinfo else pub.replace(tzinfo=UTC)
    return published_at_from_parse_extract(extract_payload)


def published_at_within_depth(final_published_at: datetime, *, threshold_utc: datetime) -> bool:
    pub = final_published_at if final_published_at.tzinfo else final_published_at.replace(tzinfo=UTC)
    pub = pub.astimezone(UTC)
    return pub >= threshold_utc


async def prepare_write_session(db: AsyncSession) -> None:
    await db.rollback()


async def list_unprocessed_by_source(
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


async def extract_single_article_for_parse_source(
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


async def execute_parse_source(
    db: AsyncSession,
    *,
    source_id: UUID,
    days: int,
    skip_undated: bool,
    created_by_id: UUID | None,
    parse_run_id: UUID | None = None,
) -> ParseSourceWorkOutcome:
    """Полный цикл разбора: discovery, extract, создание документов, обновление ``Source``."""
    from app.services.parsing.extractor import download_html, extract_article_text

    source = await db.get(Source, source_id)
    if source is None:
        raise ValueError("source_not_found")
    if not source.is_active:
        raise ValueError("source_inactive")

    await bump_parse_run_progress(db, parse_run_id, phase="discovery")

    doc_type_row = (
        await db.execute(select(DocumentType.code).where(DocumentType.id == source.document_type_id))
    ).one_or_none()
    if doc_type_row is None:
        raise ValueError("document_type_missing")
    document_type_code = doc_type_row[0]

    from app.services.parsing.rss_urls import resolve_source_rss_urls

    discovered = await discover_source_news_urls(
        source.url,
        rss_urls=resolve_source_rss_urls(
            getattr(source, "rss_urls", None),
            legacy_rss_url=getattr(source, "rss_url", None),
        ),
        discovery_paths=getattr(source, "discovery_paths", None),
        days=days,
        skip_undated=False,
    )
    await bump_parse_run_progress(db, parse_run_id, phase="extract", found_total=len(discovered))
    depth_threshold_utc = datetime.now(UTC) - timedelta(days=days)

    new_doc_ids: set[UUID] = set()
    candidates = []
    for item in discovered:
        existing = await get_document_by_source_url(db, item.url)
        if existing is None:
            candidates.append(item)

    await bump_parse_run_progress(db, parse_run_id, phase="save")

    sem = asyncio.Semaphore(PARSE_SOURCE_MAX_CONCURRENCY)

    async def _bounded_extract(item: DiscoveredUrl, idx: int):
        async with sem:
            delay = (idx % PARSE_SOURCE_MAX_CONCURRENCY) * PARSE_SOURCE_REQUEST_DELAY_SEC
            extracted = await extract_single_article_for_parse_source(
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

        final_pub = final_published_at_for_parse(item, extracted)
        if skip_undated and final_pub is None:
            continue
        if final_pub is not None and not published_at_within_depth(
            final_pub,
            threshold_utc=depth_threshold_utc,
        ):
            continue

        await prepare_write_session(db)
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

                await embed_document_if_stale(
                    db,
                    document_id=doc.id,
                    stage=EmbeddingStage.ORIGINAL,
                )
                new_doc_ids.add(doc.id)
        except ValidationError:
            await db.rollback()
            raise
        except IntegrityError:
            await db.rollback()
            continue

    await db.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(
            last_parse_at=datetime.now(UTC),
            last_parse_created_total=len(new_doc_ids),
        ),
    )
    await db.commit()
    return ParseSourceWorkOutcome(
        found_total=len(discovered),
        created_total=len(new_doc_ids),
        new_document_ids=new_doc_ids,
    )
