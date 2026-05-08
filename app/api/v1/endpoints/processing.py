from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_started_by_id
from app.core.config import settings
from app.infrastructure.db.models import Document, ProcessingJob
from app.infrastructure.db.session import get_db
from app.schemas.processing import (
    AnnotateBatchStatusResponse,
    EnqueueAnnotateMissingRequest,
    EnqueueAnnotateMissingResponse,
    EnqueueTranslateMissingRequest,
    EnqueueTranslateMissingResponse,
    TranslateBatchStatusResponse,
)
from app.services.processing.annotate_batch_store import (
    get_annotate_batch,
    inc_annotate_batch_counter,
    init_annotate_batch,
)
from app.services.processing.enqueue_locks import try_acquire_enqueue_lock
from app.services.processing.saq_queue import get_saq_annotate_queue, get_saq_translate_queue
from app.services.processing.jobs import JobStatus, JobType
from app.services.processing.translate_batch_store import (
    get_translate_batch,
    inc_translate_batch_counter,
    init_translate_batch,
)

router = APIRouter(prefix="/processing", tags=["processing"])


@router.post("/documents/translate-missing", response_model=EnqueueTranslateMissingResponse)
async def enqueue_translate_missing_documents(
    payload: EnqueueTranslateMissingRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTranslateMissingResponse:
    q = (
        select(Document.id)
        .where(
            or_(
                Document.translated_content.is_(None),
                Document.translated_content == "",
                func.btrim(Document.translated_content) == "",
            ),
            ~select(ProcessingJob.id)
            .where(
                ProcessingJob.document_id == Document.id,
                ProcessingJob.job_type == JobType.TRANSLATE,
                ProcessingJob.status.in_((JobStatus.RUNNING, JobStatus.PENDING)),
            )
            .exists(),
        )
        .order_by(Document.created_at.asc())
    )
    if payload.limit is not None:
        q = q.limit(payload.limit)
    rows = await db.execute(q)
    document_ids = [str(row.id) for row in rows]
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
            queue_job_key = f"translate-missing:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.TRANSLATE,
                status=JobStatus.PENDING,
                model_name=settings.model_translation,
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
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

    return EnqueueTranslateMissingResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/translate-missing/{batch_id}", response_model=TranslateBatchStatusResponse)
async def get_translate_missing_batch_status(batch_id: str) -> TranslateBatchStatusResponse:
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


@router.post("/documents/annotate-missing", response_model=EnqueueAnnotateMissingResponse)
async def enqueue_annotate_missing_documents(
    payload: EnqueueAnnotateMissingRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueAnnotateMissingResponse:
    q = (
        select(Document.id)
        .where(
            Document.translated_content.is_not(None),
            func.btrim(Document.translated_content) != "",
            or_(
                Document.translated_summary.is_(None),
                Document.translated_summary == "",
                func.btrim(Document.translated_summary) == "",
            ),
            ~select(ProcessingJob.id)
            .where(
                ProcessingJob.document_id == Document.id,
                ProcessingJob.job_type == JobType.SUMMARY,
                ProcessingJob.status.in_((JobStatus.RUNNING, JobStatus.PENDING)),
            )
            .exists(),
        )
        .order_by(Document.created_at.asc())
    )
    if payload.limit is not None:
        q = q.limit(payload.limit)
    rows = await db.execute(q)
    document_ids = [str(row.id) for row in rows]
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
            queue_job_key = f"annotate-missing:{batch_id}:{document_id}"
            pending_job = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.SUMMARY,
                status=JobStatus.PENDING,
                model_name=settings.model_summary,
                batch_id=batch_id,
                queue_name=queue.name,
                queue_job_key=queue_job_key,
                started_by_id=started_by_id,
            )
            db.add(pending_job)
            await db.flush()
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

    return EnqueueAnnotateMissingResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/annotate-missing/{batch_id}", response_model=AnnotateBatchStatusResponse)
async def get_annotate_missing_batch_status(batch_id: str) -> AnnotateBatchStatusResponse:
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
