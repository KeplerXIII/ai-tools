"""Постановка full LLM pipeline (общая логика для API и воркера разбора источника)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.db.models import ProcessingJob
from app.schemas.processing import EnqueueFullLlmPipelineRequest, EnqueueFullLlmPipelineResponse
from app.services.processing.enqueue_locks import release_enqueue_lock, try_acquire_enqueue_lock
from app.services.processing.full_llm_pipeline_plan import (
    FullLlmPipelinePlanEntry,
    is_pipeline_document_blocked_for_phase_a,
    map_document_pipeline_plans,
)
from app.services.processing.jobs import JobStatus, JobType, provider_label_for_task
from app.services.processing.pipeline_followup import schedule_post_translate_pipeline_jobs
from app.services.processing.processing_enqueue_queries import filter_out_active_jobs, require_documents_exist
from app.services.processing.redis_batch_store import inc_processing_batch, init_processing_batch
from app.services.processing.saq_queue import (
    get_saq_extractor_queue,
    get_saq_tagger_queue,
    get_saq_translate_queue,
)


async def enqueue_full_llm_pipeline_core(
    db: AsyncSession,
    payload: EnqueueFullLlmPipelineRequest,
    *,
    started_by_id: UUID | None,
) -> EnqueueFullLlmPipelineResponse:
    """См. ``POST /processing/documents/full-llm-pipeline``."""
    correlation_id = str(uuid.uuid4())
    all_ids = await require_documents_exist(db, payload.document_ids)
    plans = await map_document_pipeline_plans(db, document_ids=all_ids, target_lang=payload.target_lang)

    tr_free = set(await filter_out_active_jobs(db, all_ids, JobType.TRANSLATE))
    tag_orig_free = set(
        await filter_out_active_jobs(
            db,
            all_ids,
            JobType.TAG,
            queue_job_key_like="tagger-original:%",
        )
    )
    ext_free = set(await filter_out_active_jobs(db, all_ids, JobType.ENTITY_EXTRACT))

    work_documents: list[tuple[str, FullLlmPipelinePlanEntry]] = []
    skipped_blocked = 0
    skipped_already_complete = 0
    for document_id in all_ids:
        p = plans.get(document_id)
        if p is None:
            continue
        if is_pipeline_document_blocked_for_phase_a(
            p,
            document_id,
            translate_free=tr_free,
            tag_original_free=tag_orig_free,
            extractor_free=ext_free,
        ):
            skipped_blocked += 1
            continue
        phase_a = p.need_translate or p.need_tag_original or p.need_extractor
        if not phase_a and not p.need_phase_b:
            skipped_already_complete += 1
            continue
        work_documents.append((document_id, p))

    n_tr = sum(1 for _, p in work_documents if p.need_translate)
    n_tag = sum(1 for _, p in work_documents if p.need_tag_original)
    n_ext = sum(1 for _, p in work_documents if p.need_extractor)

    translate_batch_id = str(uuid.uuid4())
    tagger_batch_id = str(uuid.uuid4())
    extractor_batch_id = str(uuid.uuid4())
    if n_tr:
        await init_processing_batch("translate", translate_batch_id, scanned=n_tr)
    if n_tag:
        await init_processing_batch("tagger", tagger_batch_id, scanned=n_tag)
    if n_ext:
        await init_processing_batch("extractor", extractor_batch_id, scanned=n_ext)

    translate_queue = get_saq_translate_queue()
    tagger_queue = get_saq_tagger_queue()
    extractor_queue = get_saq_extractor_queue()
    await translate_queue.connect()
    await tagger_queue.connect()
    await extractor_queue.connect()
    enqueued = 0
    started_by = str(started_by_id) if started_by_id else None
    try:
        for document_id, p in work_documents:
            phase_a = p.need_translate or p.need_tag_original or p.need_extractor
            if not phase_a and p.need_phase_b:
                if await schedule_post_translate_pipeline_jobs(
                    document_id=document_id,
                    correlation_id=correlation_id,
                    max_tags=payload.max_tags,
                    started_by_id=started_by,
                ):
                    enqueued += 1
                continue

            acquired_locks: list[str] = []
            if p.need_translate:
                if not await try_acquire_enqueue_lock(
                    "translate",
                    document_id,
                    ttl_sec=settings.saq_translate_job_timeout_sec + 300,
                ):
                    continue
                acquired_locks.append("translate")
            if p.need_tag_original:
                if not await try_acquire_enqueue_lock(
                    "tagger_original",
                    document_id,
                    ttl_sec=settings.saq_tagger_job_timeout_sec + 300,
                ):
                    for k in reversed(acquired_locks):
                        await release_enqueue_lock(k, document_id)
                    continue
                acquired_locks.append("tagger_original")
            if p.need_extractor:
                if not await try_acquire_enqueue_lock(
                    "extractor",
                    document_id,
                    ttl_sec=settings.saq_extractor_job_timeout_sec + 300,
                ):
                    for k in reversed(acquired_locks):
                        await release_enqueue_lock(k, document_id)
                    continue
                acquired_locks.append("extractor")

            now = datetime.now(UTC)
            tag_pj: ProcessingJob | None = None
            tr_pj: ProcessingJob | None = None
            ex_pj: ProcessingJob | None = None
            tag_key = ""
            tr_key = ""
            ex_key = ""

            if p.need_tag_original:
                tag_key = f"tagger-original:{tagger_batch_id}:{document_id}"
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
                db.add(tag_pj)
            if p.need_translate:
                tr_key = f"translate:{translate_batch_id}:{document_id}"
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
                db.add(tr_pj)
            if p.need_extractor:
                ex_key = f"extractor:{extractor_batch_id}:{document_id}"
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
                db.add(ex_pj)
            await db.flush()
            await db.commit()

            tag_job = None
            tr_job = None
            ex_job = None
            if p.need_tag_original and tag_pj is not None:
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
            if p.need_translate and tr_pj is not None:
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
            if p.need_extractor and ex_pj is not None:
                ex_job = await extractor_queue.enqueue(
                    "extractor_document_job",
                    key=ex_key,
                    document_id=document_id,
                    started_by_id=started_by,
                    batch_id=extractor_batch_id,
                    processing_job_id=str(ex_pj.id),
                    timeout=settings.saq_extractor_job_timeout_sec,
                )

            want_tag = p.need_tag_original
            want_tr = p.need_translate
            want_ex = p.need_extractor
            saq_ok = True
            if want_tag:
                saq_ok = saq_ok and tag_job is not None
            if want_tr:
                saq_ok = saq_ok and tr_job is not None
            if want_ex:
                saq_ok = saq_ok and ex_job is not None

            if not saq_ok:
                if want_tag and tag_pj is not None:
                    if tag_job is None:
                        tag_pj.status = JobStatus.CANCELLED
                        tag_pj.finished_at = now
                    else:
                        await inc_processing_batch("tagger", tagger_batch_id, "enqueued")
                if want_tr and tr_pj is not None:
                    if tr_job is None:
                        tr_pj.status = JobStatus.CANCELLED
                        tr_pj.finished_at = now
                    else:
                        await inc_processing_batch("translate", translate_batch_id, "enqueued")
                if want_ex and ex_pj is not None:
                    if ex_job is None:
                        ex_pj.status = JobStatus.CANCELLED
                        ex_pj.finished_at = now
                    else:
                        await inc_processing_batch("extractor", extractor_batch_id, "enqueued")
                await db.commit()
                for k in reversed(acquired_locks):
                    await release_enqueue_lock(k, document_id)
                continue

            if want_tag:
                await inc_processing_batch("tagger", tagger_batch_id, "enqueued")
            if want_tr:
                await inc_processing_batch("translate", translate_batch_id, "enqueued")
            if want_ex:
                await inc_processing_batch("extractor", extractor_batch_id, "enqueued")
            enqueued += 1

            if p.need_phase_b and not p.need_translate:
                await schedule_post_translate_pipeline_jobs(
                    document_id=document_id,
                    correlation_id=correlation_id,
                    max_tags=payload.max_tags,
                    started_by_id=started_by,
                )
    finally:
        await translate_queue.disconnect()
        await tagger_queue.disconnect()
        await extractor_queue.disconnect()

    return EnqueueFullLlmPipelineResponse(
        pipeline_correlation_id=correlation_id,
        translate_batch_id=translate_batch_id,
        tagger_original_batch_id=tagger_batch_id,
        extractor_batch_id=extractor_batch_id,
        scanned=len(all_ids),
        enqueued=enqueued,
        skipped_blocked=skipped_blocked,
        skipped_already_complete=skipped_already_complete,
    )
