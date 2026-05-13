"""Постановка document jobs по одному типу (те же очереди/локи, что REST /processing/documents/*)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.db.models import ProcessingJob
from app.schemas.processing import (
    EnqueueAnnotateResponse,
    EnqueueCategorizeResponse,
    EnqueueExtractorResponse,
    EnqueueTaggerResponse,
    EnqueueTranslateResponse,
)
from app.services.processing.enqueue_locks import try_acquire_enqueue_lock
from app.services.processing.jobs import JobStatus, JobType, provider_label_for_task
from app.services.processing.processing_enqueue_queries import filter_out_active_jobs, require_documents_exist
from app.services.processing.redis_batch_store import inc_processing_batch, init_processing_batch
from app.services.processing.saq_queue import (
    get_saq_annotate_queue,
    get_saq_categorize_queue,
    get_saq_extractor_queue,
    get_saq_tagger_queue,
    get_saq_translate_queue,
)


async def enqueue_translate_batch(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    target_lang: str,
    started_by_id: UUID | None,
    pipeline_correlation_id: str | None = None,
    pipeline_max_tags: int = 10,
    pipeline_followup_tag_translated: bool = False,
    pipeline_followup_annotate: bool = False,
    pipeline_followup_categorize: bool = False,
) -> EnqueueTranslateResponse:
    ids = await require_documents_exist(db, document_ids)
    ids = await filter_out_active_jobs(db, ids, JobType.TRANSLATE)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("translate", batch_id, scanned=len(ids))
    queue = get_saq_translate_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in ids:
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
            await db.commit()
            payload: dict[str, object] = dict(
                document_id=document_id,
                target_lang=target_lang,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_translate_job_timeout_sec,
            )
            if pipeline_correlation_id:
                payload["pipeline_correlation_id"] = pipeline_correlation_id
                payload["pipeline_max_tags"] = pipeline_max_tags
                payload["pipeline_followup_tag_translated"] = pipeline_followup_tag_translated
                payload["pipeline_followup_annotate"] = pipeline_followup_annotate
                payload["pipeline_followup_categorize"] = pipeline_followup_categorize
            job = await queue.enqueue(
                "translate_document_job",
                key=queue_job_key,
                **payload,
            )
            if job is not None:
                enqueued += 1
                await inc_processing_batch("translate", batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()
    return EnqueueTranslateResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(ids),
        enqueued=enqueued,
    )


async def enqueue_annotate_batch(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    started_by_id: UUID | None,
) -> EnqueueAnnotateResponse:
    ids = await require_documents_exist(db, document_ids)
    ids = await filter_out_active_jobs(db, ids, JobType.SUMMARY)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("annotate", batch_id, scanned=len(ids))
    queue = get_saq_annotate_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in ids:
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
                await inc_processing_batch("annotate", batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()
    return EnqueueAnnotateResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(ids),
        enqueued=enqueued,
    )


async def enqueue_categorize_batch(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    started_by_id: UUID | None,
) -> EnqueueCategorizeResponse:
    ids = await require_documents_exist(db, document_ids)
    ids = await filter_out_active_jobs(db, ids, JobType.CATEGORIZE)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("categorize", batch_id, scanned=len(ids))
    queue = get_saq_categorize_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in ids:
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
                await inc_processing_batch("categorize", batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()
    return EnqueueCategorizeResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(ids),
        enqueued=enqueued,
    )


async def enqueue_extractor_batch(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    started_by_id: UUID | None,
) -> EnqueueExtractorResponse:
    ids = await require_documents_exist(db, document_ids)
    ids = await filter_out_active_jobs(db, ids, JobType.ENTITY_EXTRACT)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("extractor", batch_id, scanned=len(ids))
    queue = get_saq_extractor_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in ids:
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
                await inc_processing_batch("extractor", batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()
    return EnqueueExtractorResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(ids),
        enqueued=enqueued,
    )


async def enqueue_tagger_batch(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    max_tags: int,
    use_translation: bool,
    started_by_id: UUID | None,
) -> EnqueueTaggerResponse:
    source = "translated" if use_translation else "original"
    same_source_active_key_prefix = f"tagger-{source}:"

    ids = await require_documents_exist(db, document_ids)
    ids = await filter_out_active_jobs(
        db,
        ids,
        JobType.TAG,
        queue_job_key_like=f"{same_source_active_key_prefix}%",
    )
    batch_id = str(uuid.uuid4())
    await init_processing_batch("tagger", batch_id, scanned=len(ids))
    queue = get_saq_tagger_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        lock_kind = "tagger_translated" if use_translation else "tagger_original"
        for document_id in ids:
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
            await db.commit()
            job = await queue.enqueue(
                "tagger_document_job",
                key=queue_job_key,
                document_id=document_id,
                use_translation=use_translation,
                max_tags=max_tags,
                started_by_id=started_by,
                batch_id=batch_id,
                processing_job_id=str(pending_job.id),
                timeout=settings.saq_tagger_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_processing_batch("tagger", batch_id, "enqueued")
            else:
                pending_job.status = JobStatus.CANCELLED
                pending_job.finished_at = datetime.now(UTC)
                await db.commit()
    finally:
        await queue.disconnect()
    return EnqueueTaggerResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(ids),
        enqueued=enqueued,
        text_source="translated" if use_translation else "original",
    )
