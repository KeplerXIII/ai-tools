from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_started_by_id
from app.api.sse import sse_json_event
from app.infrastructure.db.models import Document, DocumentCategory, DocumentEntity, DocumentTag, ProcessingJob, Tag
from app.infrastructure.db.session import AsyncSessionLocal, get_db
from app.schemas.processing import (
    AnnotateBatchStatusResponse,
    CategorizeBatchStatusResponse,
    EnqueueAnnotateRequest,
    EnqueueAnnotateResponse,
    EnqueueCategorizeRequest,
    EnqueueCategorizeResponse,
    EnqueueExtractorRequest,
    EnqueueExtractorResponse,
    EnqueueFullLlmPipelineRequest,
    EnqueueFullLlmPipelineResponse,
    EnqueueTaggerRequest,
    EnqueueTaggerResponse,
    EnqueueTranslateRequest,
    EnqueueTranslateResponse,
    ExtractorBatchStatusResponse,
    TaggerBatchStatusResponse,
    TranslateBatchStatusResponse,
)
from app.services.processing.document_stage_enqueue import (
    enqueue_annotate_batch,
    enqueue_categorize_batch,
    enqueue_extractor_batch,
    enqueue_tagger_batch,
    enqueue_translate_batch,
)
from app.services.processing.full_llm_pipeline_enqueue import enqueue_full_llm_pipeline_core
from app.services.documents.document_embedding import collect_embedding_counters
from app.services.processing.redis_batch_store import (
    ProcessingBatchKind,
    get_processing_batch,
)

router = APIRouter(prefix="/processing", tags=["processing"])


BatchKind = ProcessingBatchKind


def _batch_status_dict(batch_id: str, payload: dict[str, int]) -> dict[str, Any]:
    """Общее тело ответа для REST и SSE (счётчики из Redis)."""
    enqueued = int(payload["enqueued"])
    completed = int(payload["completed"])
    failed = int(payload["failed"])
    skipped = int(payload["skipped"])
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0
    return {
        "ok": True,
        "batch_id": batch_id,
        "scanned": int(payload["scanned"]),
        "enqueued": enqueued,
        "completed": completed,
        "failed": failed,
        "skipped": skipped,
        "pending": pending,
        "done": done,
    }


async def _fetch_batch_store_payload(kind: BatchKind, batch_id: str) -> dict[str, int] | None:
    return await get_processing_batch(kind, batch_id)


def _job_to_dict(job: ProcessingJob) -> dict:
    return {
        "id": str(job.id),
        "document_id": str(job.document_id) if job.document_id else None,
        "source_id": str(job.source_id) if job.source_id else None,
        "job_type": job.job_type,
        "status": job.status,
        "model_name": job.model_name,
        "provider": job.provider,
        "batch_id": job.batch_id,
        "queue_name": job.queue_name,
        "queue_job_key": job.queue_job_key,
        "started_by_id": str(job.started_by_id) if job.started_by_id else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "duration_ms": job.duration_ms,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


async def _collect_dashboard_payload(session: AsyncSession) -> dict:
    jobs_rows = await session.execute(select(ProcessingJob).order_by(ProcessingJob.created_at.desc()))
    jobs = [_job_to_dict(row[0]) for row in jobs_rows]

    docs_total = int(await session.scalar(select(func.count(Document.id))) or 0)
    docs_with_translation = int(
        await session.scalar(
            select(func.count(Document.id)).where(
                Document.translated_content.is_not(None),
                func.btrim(Document.translated_content) != "",
            )
        )
        or 0
    )
    docs_with_summary = int(
        await session.scalar(
            select(func.count(Document.id)).where(
                Document.translated_summary.is_not(None),
                func.btrim(Document.translated_summary) != "",
            )
        )
        or 0
    )
    docs_categorized = int(await session.scalar(select(func.count(func.distinct(DocumentCategory.document_id)))) or 0)
    docs_with_entities = int(await session.scalar(select(func.count(func.distinct(DocumentEntity.document_id)))) or 0)

    docs_with_original_tags = int(
        await session.scalar(
            select(func.count(func.distinct(DocumentTag.document_id)))
            .select_from(DocumentTag)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .join(Document, Document.id == DocumentTag.document_id)
            .where(Tag.language_id == Document.original_language_id)
        )
        or 0
    )
    docs_with_translated_tags = int(
        await session.scalar(
            select(func.count(func.distinct(DocumentTag.document_id)))
            .select_from(DocumentTag)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .join(Document, Document.id == DocumentTag.document_id)
            .where(
                Document.translated_language_id.is_not(None),
                Tag.language_id == Document.translated_language_id,
            )
        )
        or 0
    )

    embedding_counters = await collect_embedding_counters(session)

    return {
        "jobs": jobs,
        "counters": {
            "documents_total": docs_total,
            "with_translations": docs_with_translation,
            "with_annotations": docs_with_summary,
            "categorized": docs_categorized,
            "with_entities": docs_with_entities,
            "tagged_original_lang": docs_with_original_tags,
            "tagged_translated_lang": docs_with_translated_tags,
        },
        "embedding_counters": embedding_counters,
    }


@router.post("/documents/full-llm-pipeline", response_model=EnqueueFullLlmPipelineResponse)
async def enqueue_full_llm_pipeline(
    payload: EnqueueFullLlmPipelineRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueFullLlmPipelineResponse:
    """Фаза A: только недостающие шаги (теги оригинал / перевод / сущности). Фаза B — после успешного перевода воркером или сразу из API, если перевод на ``target_lang`` уже есть."""
    return await enqueue_full_llm_pipeline_core(db, payload, started_by_id=started_by_id)


@router.post("/documents/translate", response_model=EnqueueTranslateResponse)
async def enqueue_translate_documents(
    payload: EnqueueTranslateRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTranslateResponse:
    return await enqueue_translate_batch(
        db,
        document_ids=payload.document_ids,
        target_lang=payload.target_lang,
        started_by_id=started_by_id,
    )


@router.get("/documents/translate/{batch_id}", response_model=TranslateBatchStatusResponse)
async def get_translate_batch_status(batch_id: str) -> TranslateBatchStatusResponse:
    payload = await get_processing_batch("translate", batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    return TranslateBatchStatusResponse.model_validate(_batch_status_dict(batch_id, payload))


@router.post("/documents/annotate", response_model=EnqueueAnnotateResponse)
async def enqueue_annotate_documents(
    payload: EnqueueAnnotateRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueAnnotateResponse:
    return await enqueue_annotate_batch(db, document_ids=payload.document_ids, started_by_id=started_by_id)


@router.get("/documents/annotate/{batch_id}", response_model=AnnotateBatchStatusResponse)
async def get_annotate_batch_status(batch_id: str) -> AnnotateBatchStatusResponse:
    payload = await get_processing_batch("annotate", batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    return AnnotateBatchStatusResponse.model_validate(_batch_status_dict(batch_id, payload))


@router.post("/documents/categorize", response_model=EnqueueCategorizeResponse)
async def enqueue_categorize_documents(
    payload: EnqueueCategorizeRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueCategorizeResponse:
    return await enqueue_categorize_batch(db, document_ids=payload.document_ids, started_by_id=started_by_id)


@router.get("/documents/categorize/{batch_id}", response_model=CategorizeBatchStatusResponse)
async def get_categorize_batch_status(batch_id: str) -> CategorizeBatchStatusResponse:
    payload = await get_processing_batch("categorize", batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    return CategorizeBatchStatusResponse.model_validate(_batch_status_dict(batch_id, payload))


@router.post("/documents/extractor", response_model=EnqueueExtractorResponse)
async def enqueue_extractor_documents(
    payload: EnqueueExtractorRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueExtractorResponse:
    return await enqueue_extractor_batch(db, document_ids=payload.document_ids, started_by_id=started_by_id)


@router.get("/documents/extractor/{batch_id}", response_model=ExtractorBatchStatusResponse)
async def get_extractor_batch_status(batch_id: str) -> ExtractorBatchStatusResponse:
    payload = await get_processing_batch("extractor", batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    return ExtractorBatchStatusResponse.model_validate(_batch_status_dict(batch_id, payload))


async def _enqueue_tagger_documents(
    *,
    payload: EnqueueTaggerRequest,
    use_translation: bool,
    db: AsyncSession,
    started_by_id: UUID | None,
) -> EnqueueTaggerResponse:
    return await enqueue_tagger_batch(
        db,
        document_ids=payload.document_ids,
        max_tags=payload.max_tags,
        use_translation=use_translation,
        started_by_id=started_by_id,
    )


@router.post("/documents/tagger-original", response_model=EnqueueTaggerResponse)
async def enqueue_tagger_original_documents(
    payload: EnqueueTaggerRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTaggerResponse:
    return await _enqueue_tagger_documents(
        payload=payload,
        use_translation=False,
        db=db,
        started_by_id=started_by_id,
    )


@router.post("/documents/tagger-translated", response_model=EnqueueTaggerResponse)
async def enqueue_tagger_translated_documents(
    payload: EnqueueTaggerRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTaggerResponse:
    return await _enqueue_tagger_documents(
        payload=payload,
        use_translation=True,
        db=db,
        started_by_id=started_by_id,
    )


@router.get("/documents/tagger/{batch_id}", response_model=TaggerBatchStatusResponse)
async def get_tagger_batch_status(batch_id: str) -> TaggerBatchStatusResponse:
    payload = await get_processing_batch("tagger", batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    return TaggerBatchStatusResponse.model_validate(_batch_status_dict(batch_id, payload))


@router.get("/batches/{batch_id}/stream")
async def stream_batch_status(
    batch_id: str,
    kind: BatchKind = Query(..., description="Тип батча (очередь)"),
) -> StreamingResponse:
    """SSE: прогресс батча до ``done`` (для тостов без polling)."""

    async def event_stream():
        previous_json: str | None = None
        while True:
            try:
                raw = await _fetch_batch_store_payload(kind, batch_id)
                if raw is None:
                    yield sse_json_event("error", {"message": "Батч не найден"})
                    return
                body = {
                    **_batch_status_dict(batch_id, raw),
                    "snapshot_at": datetime.now(UTC).isoformat(),
                    "kind": kind,
                }
                stable = json.dumps(body, ensure_ascii=False, sort_keys=True, default=str)
                if stable != previous_json:
                    yield sse_json_event("snapshot", body)
                    previous_json = stable
                if body["done"]:
                    return
                yield b"event: heartbeat\ndata: ping\n\n"
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                yield sse_json_event("error", {"message": str(exc)})
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


@router.get("/dashboard/stream")
async def stream_processing_dashboard() -> StreamingResponse:
    async def event_stream():
        previous_stable_payload_json: str | None = None
        while True:
            try:
                async with AsyncSessionLocal() as session:
                    stable_payload = await _collect_dashboard_payload(session)
                stable_payload_json = json.dumps(stable_payload, ensure_ascii=False, sort_keys=True)
                if stable_payload_json != previous_stable_payload_json:
                    snapshot_payload = {
                        "snapshot_at": datetime.now(UTC).isoformat(),
                        **stable_payload,
                    }
                    yield sse_json_event("snapshot", snapshot_payload)
                    previous_stable_payload_json = stable_payload_json
                else:
                    yield b"event: heartbeat\ndata: ping\n\n"
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                yield sse_json_event("error", {"message": str(exc)})
                await asyncio.sleep(2)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Disable buffering in nginx/compatible proxies for low-latency SSE delivery.
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/debug/documents/purge")
async def purge_all_documents_for_debug(
    db: AsyncSession = Depends(get_db),
) -> dict[str, int | bool]:
    # Debug helper: delete all documents. Related rows are removed by FK ON DELETE CASCADE.
    deleted = await db.execute(delete(Document))
    await db.commit()
    return {
        "ok": True,
        "deleted_documents": int(deleted.rowcount or 0),
    }
