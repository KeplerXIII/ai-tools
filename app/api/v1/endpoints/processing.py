from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_started_by_id
from app.api.sse import sse_json_event
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
from app.services.processing.enqueue_locks import release_enqueue_lock, try_acquire_enqueue_lock
from app.services.processing.processing_enqueue_queries import (
    filter_out_active_jobs,
    require_documents_exist,
)
from app.services.processing.jobs import JobStatus, JobType, provider_label_for_task
from app.services.processing.redis_batch_store import (
    ProcessingBatchKind,
    get_processing_batch,
    inc_processing_batch,
    init_processing_batch,
)
from app.services.processing.saq_queue import (
    get_saq_annotate_queue,
    get_saq_categorize_queue,
    get_saq_extractor_queue,
    get_saq_tagger_queue,
    get_saq_translate_queue,
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


@router.post("/documents/full-llm-pipeline", response_model=EnqueueFullLlmPipelineResponse)
async def enqueue_full_llm_pipeline(
    payload: EnqueueFullLlmPipelineRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueFullLlmPipelineResponse:
    """Фаза A параллельно: теги оригинал, перевод, сущности. После успешного перевода — фаза B (теги перевода, аннотация, категоризация)."""
    correlation_id = str(uuid.uuid4())
    all_ids = await require_documents_exist(db, payload.document_ids)
    tr_free = set(await filter_out_active_jobs(db, all_ids, JobType.TRANSLATE))
    tag_free = set(
        await filter_out_active_jobs(
            db,
            all_ids,
            JobType.TAG,
            queue_job_key_like="tagger-original:%",
        )
    )
    ext_free = set(await filter_out_active_jobs(db, all_ids, JobType.ENTITY_EXTRACT))
    eligible = [d for d in all_ids if d in tr_free and d in tag_free and d in ext_free]

    translate_batch_id = str(uuid.uuid4())
    tagger_batch_id = str(uuid.uuid4())
    extractor_batch_id = str(uuid.uuid4())
    await init_processing_batch("translate", translate_batch_id, scanned=len(eligible))
    await init_processing_batch("tagger", tagger_batch_id, scanned=len(eligible))
    await init_processing_batch("extractor", extractor_batch_id, scanned=len(eligible))

    translate_queue = get_saq_translate_queue()
    tagger_queue = get_saq_tagger_queue()
    extractor_queue = get_saq_extractor_queue()
    await translate_queue.connect()
    await tagger_queue.connect()
    await extractor_queue.connect()
    enqueued = 0
    started_by = str(started_by_id) if started_by_id else None
    try:
        for document_id in eligible:
            if not await try_acquire_enqueue_lock(
                "translate",
                document_id,
                ttl_sec=settings.saq_translate_job_timeout_sec + 300,
            ):
                continue
            if not await try_acquire_enqueue_lock(
                "tagger_original",
                document_id,
                ttl_sec=settings.saq_tagger_job_timeout_sec + 300,
            ):
                await release_enqueue_lock("translate", document_id)
                continue
            if not await try_acquire_enqueue_lock(
                "extractor",
                document_id,
                ttl_sec=settings.saq_extractor_job_timeout_sec + 300,
            ):
                await release_enqueue_lock("translate", document_id)
                await release_enqueue_lock("tagger_original", document_id)
                continue

            now = datetime.now(UTC)
            tag_key = f"tagger-original:{tagger_batch_id}:{document_id}"
            tr_key = f"translate:{translate_batch_id}:{document_id}"
            ex_key = f"extractor:{extractor_batch_id}:{document_id}"

            tag_pj = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.TAG,
                status=JobStatus.PENDING,
                model_name=settings.model_tagging,
                provider=provider_label_for_task(LLMTask.TAGGING),
                batch_id=tagger_batch_id,
                queue_name=tagger_queue.name,
                queue_job_key=tag_key,
                started_by_id=started_by_id,
            )
            tr_pj = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.TRANSLATE,
                status=JobStatus.PENDING,
                model_name=settings.model_translation,
                provider=provider_label_for_task(LLMTask.TRANSLATION),
                batch_id=translate_batch_id,
                queue_name=translate_queue.name,
                queue_job_key=tr_key,
                started_by_id=started_by_id,
            )
            ex_pj = ProcessingJob(
                document_id=UUID(document_id),
                job_type=JobType.ENTITY_EXTRACT,
                status=JobStatus.PENDING,
                model_name=settings.model_entity_extraction,
                provider=provider_label_for_task(LLMTask.ENTITY_EXTRACTION),
                batch_id=extractor_batch_id,
                queue_name=extractor_queue.name,
                queue_job_key=ex_key,
                started_by_id=started_by_id,
            )
            db.add(tag_pj)
            db.add(tr_pj)
            db.add(ex_pj)
            await db.flush()
            await db.commit()

            tag_job = await tagger_queue.enqueue(
                "tagger_document_job",
                key=tag_key,
                document_id=document_id,
                use_translation=False,
                max_tags=payload.max_tags,
                started_by_id=started_by,
                batch_id=tagger_batch_id,
                processing_job_id=str(tag_pj.id),
                timeout=settings.saq_tagger_job_timeout_sec,
            )
            tr_job = await translate_queue.enqueue(
                "translate_document_job",
                key=tr_key,
                document_id=document_id,
                target_lang=payload.target_lang,
                started_by_id=started_by,
                batch_id=translate_batch_id,
                processing_job_id=str(tr_pj.id),
                pipeline_correlation_id=correlation_id,
                pipeline_max_tags=payload.max_tags,
                timeout=settings.saq_translate_job_timeout_sec,
            )
            ex_job = await extractor_queue.enqueue(
                "extractor_document_job",
                key=ex_key,
                document_id=document_id,
                started_by_id=started_by,
                batch_id=extractor_batch_id,
                processing_job_id=str(ex_pj.id),
                timeout=settings.saq_extractor_job_timeout_sec,
            )

            ok = tag_job is not None and tr_job is not None and ex_job is not None
            if not ok:
                if tag_job is None:
                    tag_pj.status = JobStatus.CANCELLED
                    tag_pj.finished_at = now
                    await release_enqueue_lock("tagger_original", document_id)
                else:
                    await inc_processing_batch("tagger", tagger_batch_id, "enqueued")
                if tr_job is None:
                    tr_pj.status = JobStatus.CANCELLED
                    tr_pj.finished_at = now
                    await release_enqueue_lock("translate", document_id)
                else:
                    await inc_processing_batch("translate", translate_batch_id, "enqueued")
                if ex_job is None:
                    ex_pj.status = JobStatus.CANCELLED
                    ex_pj.finished_at = now
                    await release_enqueue_lock("extractor", document_id)
                else:
                    await inc_processing_batch("extractor", extractor_batch_id, "enqueued")
                await db.commit()
                continue

            await inc_processing_batch("tagger", tagger_batch_id, "enqueued")
            await inc_processing_batch("translate", translate_batch_id, "enqueued")
            await inc_processing_batch("extractor", extractor_batch_id, "enqueued")
            enqueued += 1
    finally:
        await translate_queue.disconnect()
        await tagger_queue.disconnect()
        await extractor_queue.disconnect()

    return EnqueueFullLlmPipelineResponse(
        pipeline_correlation_id=correlation_id,
        translate_batch_id=translate_batch_id,
        tagger_original_batch_id=tagger_batch_id,
        extractor_batch_id=extractor_batch_id,
        scanned=len(eligible),
        enqueued=enqueued,
    )


@router.post("/documents/translate", response_model=EnqueueTranslateResponse)
async def enqueue_translate_documents(
    payload: EnqueueTranslateRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTranslateResponse:
    document_ids = await require_documents_exist(db, payload.document_ids)
    document_ids = await filter_out_active_jobs(db, document_ids, JobType.TRANSLATE)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("translate", batch_id, scanned=len(document_ids))

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
        scanned=len(document_ids),
        enqueued=enqueued,
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
    document_ids = await require_documents_exist(db, payload.document_ids)
    document_ids = await filter_out_active_jobs(db, document_ids, JobType.SUMMARY)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("annotate", batch_id, scanned=len(document_ids))

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
        scanned=len(document_ids),
        enqueued=enqueued,
    )


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
    document_ids = await require_documents_exist(db, payload.document_ids)
    document_ids = await filter_out_active_jobs(db, document_ids, JobType.CATEGORIZE)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("categorize", batch_id, scanned=len(document_ids))

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
        scanned=len(document_ids),
        enqueued=enqueued,
    )


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
    document_ids = await require_documents_exist(db, payload.document_ids)
    document_ids = await filter_out_active_jobs(db, document_ids, JobType.ENTITY_EXTRACT)
    batch_id = str(uuid.uuid4())
    await init_processing_batch("extractor", batch_id, scanned=len(document_ids))

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
        scanned=len(document_ids),
        enqueued=enqueued,
    )


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
    source = "translated" if use_translation else "original"
    same_source_active_key_prefix = f"tagger-{source}:"

    document_ids = await require_documents_exist(db, payload.document_ids)
    document_ids = await filter_out_active_jobs(
        db,
        document_ids,
        JobType.TAG,
        queue_job_key_like=f"{same_source_active_key_prefix}%",
    )
    batch_id = str(uuid.uuid4())
    await init_processing_batch("tagger", batch_id, scanned=len(document_ids))

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
