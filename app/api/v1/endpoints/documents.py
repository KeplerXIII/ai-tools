from __future__ import annotations

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
from app.domain.errors import AppError
from app.infrastructure.db.models import Document, DocumentStatus, DocumentStatusAssignment, User
from app.infrastructure.db.session import AsyncSessionLocal, get_db
from app.schemas.documents import (
    DocumentExtractResponse,
    DocumentRefineSummaryRequest,
    DocumentRefineSummaryResponse,
    DocumentStatusAssignRequest,
    DocumentStatusesResponse,
    DocumentStatusItem,
    DocumentSummaryRequest,
    DocumentSummaryResponse,
    DocumentTagRequest,
    DocumentTranslateRequest,
    DocumentUpdateRequest,
    ExtractUrlPersistRequest,
    SummarySource,
)
from app.schemas.extract import ImageInfo
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


def _images_from_extract(data: dict[str, Any]) -> list[ImageInfo]:
    out: list[ImageInfo] = []
    for x in data.get("images") or []:
        if not isinstance(x, dict):
            continue
        u = x.get("url")
        if not u:
            continue
        out.append(ImageInfo(url=str(u), alt=x.get("alt"), title=x.get("title")))
    return out




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
        return document_to_extract_response(existing, from_cache=True)

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
            ver = doc.version
    except IntegrityError:
        await db.rollback()
        existing2 = await get_document_by_source_url(db, url_str)
        if existing2:
            return document_to_extract_response(existing2, from_cache=True)
        raise

    return DocumentExtractResponse(
        title=data.get("title") or None,
        author=data.get("author"),
        date=data.get("date"),
        url=data.get("url"),
        text=data["text"],
        length=data["length"],
        method=data["method"],
        quality=data["quality"],
        needs_review=data["needs_review"],
        images=_images_from_extract(data),
        main_image=(str(data["main_image"]) if data.get("main_image") else None),
        document_id=doc_id,
        from_cache=False,
        version=ver,
    )


def _handle(exc: AppError):
    raise map_app_error(exc) from exc


@router.get("/{document_id}/statuses", response_model=DocumentStatusesResponse)
async def document_statuses(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    doc = await db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Документ не найден")

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
    statuses = [
        DocumentStatusItem(
            code=row.code,
            name_ru=row.name_ru,
            description=row.description,
            assigned_at=row.assigned_at,
            assigned_by_id=row.assigned_by_id,
        )
        for row in result
    ]
    return DocumentStatusesResponse(document_id=document_id, statuses=statuses)


@router.post("/{document_id}/statuses")
async def assign_document_status(
    document_id: UUID,
    payload: DocumentStatusAssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
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
        stmt = insert(DocumentStatusAssignment).values(
            document_id=document_id,
            status_id=status_id,
            assigned_by_id=user.id,
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


@router.post("/{document_id}/entities")
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
    return {"ok": True, "document_id": str(document_id)}


@router.post("/{document_id}/categorize")
async def document_categorize(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    started_by_id = user.id if user else None
    try:
        await _prepare_write_session(db)
        async with db.begin():
            await run_categorize_document(
                db,
                document_id=document_id,
                started_by_id=started_by_id,
            )
    except AppError as exc:
        _handle(exc)
    return {"ok": True, "document_id": str(document_id)}


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
