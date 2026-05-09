from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_started_by_id
from app.core.config import settings
from app.core.llm_task import LLMTask
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
    EnqueueTaggerRequest,
    EnqueueTaggerResponse,
    EnqueueTranslateRequest,
    EnqueueTranslateResponse,
    ExtractorBatchStatusResponse,
    TaggerBatchStatusResponse,
    TranslateBatchStatusResponse,
)
from app.services.processing.annotate_batch_store import (
    get_annotate_batch,
    inc_annotate_batch_counter,
    init_annotate_batch,
)
from app.services.processing.categorize_batch_store import (
    get_categorize_batch,
    inc_categorize_batch_counter,
    init_categorize_batch,
)
from app.services.processing.enqueue_locks import try_acquire_enqueue_lock
from app.services.processing.extractor_batch_store import (
    get_extractor_batch,
    inc_extractor_batch_counter,
    init_extractor_batch,
)
from app.services.processing.saq_queue import (
    get_saq_annotate_queue,
    get_saq_categorize_queue,
    get_saq_extractor_queue,
    get_saq_tagger_queue,
    get_saq_translate_queue,
)
from app.services.processing.jobs import JobStatus, JobType, provider_label_for_task
from app.services.processing.tagger_batch_store import (
    get_tagger_batch,
    inc_tagger_batch_counter,
    init_tagger_batch,
)
from app.services.processing.translate_batch_store import (
    get_translate_batch,
    inc_translate_batch_counter,
    init_translate_batch,
)

router = APIRouter(prefix="/processing", tags=["processing"])


def _dedupe_document_ids_preserve_order(document_ids: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(document_ids))


async def _require_documents_exist(db: AsyncSession, document_ids: list[UUID]) -> list[str]:
    ordered = _dedupe_document_ids_preserve_order(document_ids)
    if not ordered:
        raise HTTPException(status_code=422, detail="Список document_ids пуст")
    rows = (await db.scalars(select(Document.id).where(Document.id.in_(ordered)))).all()
    found: set[UUID] = set(rows)
    missing = [str(i) for i in ordered if i not in found]
    if missing:
        head = ", ".join(missing[:20])
        suffix = "…" if len(missing) > 20 else ""
        raise HTTPException(
            status_code=422,
            detail=f"Документы не найдены: {head}{suffix}",
        )
    return [str(i) for i in ordered]


async def _filter_out_active_jobs(
    db: AsyncSession,
    document_ids: list[str],
    job_type: JobType,
    *,
    queue_job_key_like: str | None = None,
) -> list[str]:
    if not document_ids:
        return []
    uuids = [UUID(d) for d in document_ids]
    stmt = select(ProcessingJob.document_id).where(
        ProcessingJob.document_id.in_(uuids),
        ProcessingJob.job_type == job_type,
        ProcessingJob.status.in_((JobStatus.RUNNING, JobStatus.PENDING)),
    )
    if queue_job_key_like is not None:
        stmt = stmt.where(ProcessingJob.queue_job_key.like(queue_job_key_like))
    busy = set((await db.scalars(stmt)).all())
    return [d for d in document_ids if UUID(d) not in busy]


def _sse_event(event: str, payload: dict) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _job_to_dict(job: ProcessingJob) -> dict:
    return {
        "id": str(job.id),
        "document_id": str(job.document_id),
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
    }


@router.post("/documents/translate", response_model=EnqueueTranslateResponse)
async def enqueue_translate_documents(
    payload: EnqueueTranslateRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTranslateResponse:
    document_ids = await _require_documents_exist(db, payload.document_ids)
    document_ids = await _filter_out_active_jobs(db, document_ids, JobType.TRANSLATE)
    batch_id = str(uuid.uuid4())
    await init_translate_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_translate_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in document_ids:
            lock_acquired = await try_acquire_enqueue_lock(
                "translate",
                document_id,
                ttl_sec=settings.saq_translate_job_timeout_sec + 300,
            )
            if not lock_acquired:
                continue
            queue_job_key = f"translate:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.TRANSLATE,
                status=JobStatus.PENDING,
                model_name=settings.model_translation,
                provider=provider_label_for_task(LLMTask.TRANSLATION),
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
            # Commit before enqueue so workers see processing_job_id (same as tagger).
            await db.commit()
            job = await queue.enqueue(
                "translate_document_job",
                key=queue_job_key,
                document_id=document_id,
                target_lang=payload.target_lang,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_translate_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_translate_batch_counter(batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()

    return EnqueueTranslateResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/translate/{batch_id}", response_model=TranslateBatchStatusResponse)
async def get_translate_batch_status(batch_id: str) -> TranslateBatchStatusResponse:
    payload = await get_translate_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return TranslateBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
    )


@router.post("/documents/annotate", response_model=EnqueueAnnotateResponse)
async def enqueue_annotate_documents(
    payload: EnqueueAnnotateRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueAnnotateResponse:
    document_ids = await _require_documents_exist(db, payload.document_ids)
    document_ids = await _filter_out_active_jobs(db, document_ids, JobType.SUMMARY)
    batch_id = str(uuid.uuid4())
    await init_annotate_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_annotate_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in document_ids:
            lock_acquired = await try_acquire_enqueue_lock(
                "annotate",
                document_id,
                ttl_sec=settings.saq_annotate_job_timeout_sec + 300,
            )
            if not lock_acquired:
                continue
            queue_job_key = f"annotate:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.SUMMARY,
                status=JobStatus.PENDING,
                model_name=settings.model_summary,
                provider=provider_label_for_task(LLMTask.SUMMARY),
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
            await db.commit()
            job = await queue.enqueue(
                "annotate_document_job",
                key=queue_job_key,
                document_id=document_id,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_annotate_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_annotate_batch_counter(batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()

    return EnqueueAnnotateResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/annotate/{batch_id}", response_model=AnnotateBatchStatusResponse)
async def get_annotate_batch_status(batch_id: str) -> AnnotateBatchStatusResponse:
    payload = await get_annotate_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return AnnotateBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
    )


@router.post("/documents/categorize", response_model=EnqueueCategorizeResponse)
async def enqueue_categorize_documents(
    payload: EnqueueCategorizeRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueCategorizeResponse:
    document_ids = await _require_documents_exist(db, payload.document_ids)
    document_ids = await _filter_out_active_jobs(db, document_ids, JobType.CATEGORIZE)
    batch_id = str(uuid.uuid4())
    await init_categorize_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_categorize_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in document_ids:
            lock_acquired = await try_acquire_enqueue_lock(
                "categorize",
                document_id,
                ttl_sec=settings.saq_categorize_job_timeout_sec + 300,
            )
            if not lock_acquired:
                continue
            queue_job_key = f"categorize:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.CATEGORIZE,
                status=JobStatus.PENDING,
                model_name=settings.model_categorization,
                provider=provider_label_for_task(LLMTask.CATEGORIZATION),
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
            await db.commit()
            job = await queue.enqueue(
                "categorize_document_job",
                key=queue_job_key,
                document_id=document_id,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_categorize_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_categorize_batch_counter(batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()

    return EnqueueCategorizeResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/categorize/{batch_id}", response_model=CategorizeBatchStatusResponse)
async def get_categorize_batch_status(batch_id: str) -> CategorizeBatchStatusResponse:
    payload = await get_categorize_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return CategorizeBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
    )


@router.post("/documents/extractor", response_model=EnqueueExtractorResponse)
async def enqueue_extractor_documents(
    payload: EnqueueExtractorRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueExtractorResponse:
    document_ids = await _require_documents_exist(db, payload.document_ids)
    document_ids = await _filter_out_active_jobs(db, document_ids, JobType.ENTITY_EXTRACT)
    batch_id = str(uuid.uuid4())
    await init_extractor_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_extractor_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in document_ids:
            lock_acquired = await try_acquire_enqueue_lock(
                "extractor",
                document_id,
                ttl_sec=settings.saq_extractor_job_timeout_sec + 300,
            )
            if not lock_acquired:
                continue
            queue_job_key = f"extractor:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.ENTITY_EXTRACT,
                status=JobStatus.PENDING,
                model_name=settings.model_entity_extraction,
                provider=provider_label_for_task(LLMTask.ENTITY_EXTRACTION),
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
            await db.commit()
            job = await queue.enqueue(
                "extractor_document_job",
                key=queue_job_key,
                document_id=document_id,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_extractor_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_extractor_batch_counter(batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()

    return EnqueueExtractorResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/extractor/{batch_id}", response_model=ExtractorBatchStatusResponse)
async def get_extractor_batch_status(batch_id: str) -> ExtractorBatchStatusResponse:
    payload = await get_extractor_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return ExtractorBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
    )


async def _enqueue_tagger_documents(
    *,
    payload: EnqueueTaggerRequest,
    use_translation: bool,
    db: AsyncSession,
    started_by_id: UUID | None,
) -> EnqueueTaggerResponse:
    source = "translated" if use_translation else "original"
    same_source_active_key_prefix = f"tagger-{source}:"

    document_ids = await _require_documents_exist(db, payload.document_ids)
    document_ids = await _filter_out_active_jobs(
        db,
        document_ids,
        JobType.TAG,
        queue_job_key_like=f"{same_source_active_key_prefix}%",
    )
    batch_id = str(uuid.uuid4())
    await init_tagger_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_tagger_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        lock_kind = "tagger_translated" if use_translation else "tagger_original"
        for document_id in document_ids:
            lock_acquired = await try_acquire_enqueue_lock(
                lock_kind,
                document_id,
                ttl_sec=settings.saq_tagger_job_timeout_sec + 300,
            )
            if not lock_acquired:
                continue
            queue_job_key = f"tagger-{source}:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.TAG,
                status=JobStatus.PENDING,
                model_name=settings.model_tagging,
                provider=provider_label_for_task(LLMTask.TAGGING),
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
            # Commit pending job first, so worker can reliably see processing_job_id.
            await db.commit()
            job = await queue.enqueue(
                "tagger_document_job",
                key=queue_job_key,
                document_id=document_id,
                use_translation=use_translation,
                max_tags=payload.max_tags,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_tagger_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_tagger_batch_counter(batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()

    return EnqueueTaggerResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
        text_source="translated" if use_translation else "original",
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
    payload = await get_tagger_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return TaggerBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
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
                    yield _sse_event("snapshot", snapshot_payload)
                    previous_stable_payload_json = stable_payload_json
                else:
                    yield b"event: heartbeat\ndata: ping\n\n"
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                yield _sse_event("error", {"message": str(exc)})
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
