from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.core.config import settings
from app.infrastructure.db.models import (
    Country,
    Document,
    DocumentStatus,
    DocumentStatusAssignment,
    DocumentType,
    Language,
    ProcessingJob,
    Source,
    SourceParseRun,
    User,
)
from app.infrastructure.db.session import AsyncSessionLocal, get_db
from app.schemas.parsing import (
    ActiveParseRunItem,
    ActiveParseRunsResponse,
    CountryCatalogItem,
    LanguageCatalogItem,
    ParseSourceDocumentItem,
    ParseSourceEnqueueResponse,
    ParseSourceRequest,
    ParseSourceRunResponse,
    SourceCreateRequest,
    SourceCreateResponse,
    SourceListItem,
    SourceListResponse,
)
from app.services.documents.db_refs import document_type_id_by_code
from app.services.documents.url_norm import normalize_source_url
from app.services.parsing.parse_source_runner import list_unprocessed_by_source
from app.services.processing.jobs import JobStatus, JobType
from app.services.processing.saq_queue import get_saq_parse_queue

router = APIRouter(prefix="/parsing", tags=["parsing"])


def _sse_event(event: str, payload: dict) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


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


async def _parse_run_to_response(db: AsyncSession, run: SourceParseRun) -> ParseSourceRunResponse:
    existing: list[ParseSourceDocumentItem] = []
    new_items: list[ParseSourceDocumentItem] = []
    if run.status == "completed" and run.new_document_ids:
        new_ids = {UUID(x) for x in run.new_document_ids}
        existing = await list_unprocessed_by_source(db, source_id=run.source_id)
        new_items = await list_unprocessed_by_source(db, source_id=run.source_id, document_ids=new_ids)
    elif run.status == "completed":
        existing = await list_unprocessed_by_source(db, source_id=run.source_id)

    return ParseSourceRunResponse(
        parse_run_id=run.id,
        source_id=run.source_id,
        processing_job_id=run.processing_job_id,
        phase=run.phase,
        status=cast(Literal["pending", "running", "completed", "failed"], run.status),
        found_total=run.found_total,
        created_total=run.created_total,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        existing_unprocessed_by_source=existing,
        new_unprocessed_by_source=new_items,
    )


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


@router.get("/sources/active-parse-runs", response_model=ActiveParseRunsResponse)
async def list_active_source_parse_runs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Запуски разбора в ``pending`` / ``running`` по доступным источникам (для возврата на страницу без SSE в памяти)."""
    stmt = (
        select(SourceParseRun)
        .join(Source, Source.id == SourceParseRun.source_id)
        .where(SourceParseRun.status.in_(("pending", "running")))
        .order_by(SourceParseRun.created_at.desc())
    )
    if not user.is_admin:
        stmt = stmt.where(Source.user_id == user.id)
    rows = (await db.execute(stmt)).scalars().all()
    seen_sources: set[UUID] = set()
    out: list[ActiveParseRunItem] = []
    for run in rows:
        if run.source_id in seen_sources:
            continue
        seen_sources.add(run.source_id)
        body = await _parse_run_to_response(db, run)
        out.append(ActiveParseRunItem(source_id=run.source_id, parse_run=body))
    return ActiveParseRunsResponse(items=out)


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


@router.post(
    "/sources/parse",
    response_model=ParseSourceEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def parse_source(
    payload: ParseSourceRequest,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    source = await db.get(Source, payload.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if not source.is_active:
        raise HTTPException(status_code=400, detail="Источник неактивен")
    if user is not None and not user.is_admin and source.user_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к источнику")

    doc_type_row = (
        await db.execute(select(DocumentType.code).where(DocumentType.id == source.document_type_id))
    ).one_or_none()
    if doc_type_row is None:
        raise HTTPException(status_code=500, detail="У источника не задан тип документа")

    run = SourceParseRun(
        source_id=source.id,
        status="pending",
        phase="queued",
        days=payload.days,
        skip_undated=payload.skip_undated,
        created_by_id=user.id if user else None,
    )
    db.add(run)
    await db.flush()

    pj = ProcessingJob(
        document_id=None,
        source_id=source.id,
        job_type=JobType.PARSE_SOURCE,
        status=JobStatus.PENDING,
        model_name="source-parse",
        provider="parser",
        batch_id=None,
        queue_name=settings.saq_parse_queue_name,
        queue_job_key=f"parse_source:{run.id}",
        started_by_id=user.id if user else None,
    )
    db.add(pj)
    await db.flush()
    run.processing_job_id = pj.id
    await db.commit()

    queue = get_saq_parse_queue()
    await queue.connect()
    try:
        job = await queue.enqueue(
            "parse_source_job",
            key=f"parse_source:{run.id}",
            parse_run_id=str(run.id),
            timeout=settings.saq_parse_job_timeout_sec,
        )
    finally:
        await queue.disconnect()

    if job is None:
        failed_run = await db.get(SourceParseRun, run.id)
        failed_pj = await db.get(ProcessingJob, pj.id)
        if failed_run is not None:
            failed_run.status = "failed"
            failed_run.finished_at = datetime.now(UTC)
            failed_run.phase = "failed"
            failed_run.error_message = "Не удалось поставить задачу в очередь (enqueue вернул None)"
        if failed_pj is not None:
            failed_pj.status = JobStatus.FAILED
            failed_pj.finished_at = datetime.now(UTC)
            failed_pj.error_message = "enqueue вернул None"
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Очередь разбора недоступна, попробуйте позже",
        )

    return ParseSourceEnqueueResponse(
        parse_run_id=run.id,
        source_id=source.id,
        processing_job_id=pj.id,
        status="pending",
    )


@router.get("/sources/parse-runs/{parse_run_id}/stream")
async def stream_parse_source_run(
    parse_run_id: UUID,
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """SSE: статус и фаза разбора источника (без polling)."""

    async def event_stream():
        async with AsyncSessionLocal() as session:
            run0 = await session.get(SourceParseRun, parse_run_id)
            if run0 is None:
                yield _sse_event("error", {"message": "Запуск разбора не найден"})
                return
            src0 = await session.get(Source, run0.source_id)
            if src0 is None:
                yield _sse_event("error", {"message": "Источник не найден"})
                return
            if not user.is_admin and src0.user_id != user.id:
                yield _sse_event("error", {"message": "Нет доступа"})
                return

        previous_json: str | None = None
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    run = await session.get(SourceParseRun, parse_run_id)
                    if run is None:
                        yield _sse_event("error", {"message": "Запуск разбора удалён"})
                        return
                    body = await _parse_run_to_response(session, run)
                payload = {
                    "snapshot_at": datetime.now(UTC).isoformat(),
                    **body.model_dump(mode="json"),
                }
                stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
                if stable != previous_json:
                    yield _sse_event("snapshot", payload)
                    previous_json = stable
                if run.status in ("completed", "failed"):
                    return
                yield b"event: heartbeat\ndata: ping\n\n"
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                yield _sse_event("error", {"message": str(exc)})
                await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/sources/parse-runs/{parse_run_id}", response_model=ParseSourceRunResponse)
async def get_parse_source_run(
    parse_run_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    run = await db.get(SourceParseRun, parse_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Запуск разбора не найден")
    source = await db.get(Source, run.source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Источник не найден")
    if not user.is_admin and source.user_id != user.id:
        raise HTTPException(status_code=403, detail="Нет доступа к этому запуску разбора")

    return await _parse_run_to_response(db, run)
