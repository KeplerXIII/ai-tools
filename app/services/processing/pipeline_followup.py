"""Постановка фазы B LLM-пайплайна после успешного перевода (теги по переводу, аннотация, категоризация)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from redis import asyncio as aioredis
from sqlalchemy import select

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.db.models import Document, ProcessingJob
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.processing.enqueue_locks import release_enqueue_lock, try_acquire_enqueue_lock
from app.services.processing.jobs import JobStatus, JobType, provider_label_for_task
from app.services.processing.processing_enqueue_queries import filter_out_active_jobs
from app.services.processing.redis_batch_store import inc_processing_batch, init_processing_batch
from app.services.processing.saq_queue import (
    get_saq_annotate_queue,
    get_saq_categorize_queue,
    get_saq_tagger_queue,
)

_FOLLOWUP_KEY_PREFIX = "processing:pipeline_followup_enqueued:"


def _followup_redis_key(*, correlation_id: str, document_id: str) -> str:
    return f"{_FOLLOWUP_KEY_PREFIX}{correlation_id}:{document_id}"


async def try_claim_pipeline_followup_once(*, correlation_id: str, document_id: str) -> bool:
    """True — первый колбэк по этому correlation; False — повтор SAQ или дубль."""
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _followup_redis_key(correlation_id=correlation_id, document_id=document_id)
    try:
        ok = await redis.set(key, "1", ex=7 * 24 * 60 * 60, nx=True)
        return bool(ok)
    finally:
        await redis.aclose()


async def release_pipeline_followup_claim(*, correlation_id: str, document_id: str) -> None:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _followup_redis_key(correlation_id=correlation_id, document_id=document_id)
    try:
        await redis.delete(key)
    finally:
        await redis.aclose()


async def schedule_post_translate_pipeline_jobs(
    *,
    document_id: str,
    correlation_id: str,
    max_tags: int,
    started_by_id: str | None,
    want_tag_translated: bool = True,
    want_annotate: bool = True,
    want_categorize: bool = True,
) -> bool:
    """Ставит выбранные джобы фазы B на один документ (после успешного перевода).

    Если ни один тип не нужен — сразу False (без claim в Redis).

    Возвращает True, если хотя бы одна задача реально ушла в SAQ.
    """
    want_tag_translated_b = bool(want_tag_translated)
    want_annotate_b = bool(want_annotate)
    want_categorize_b = bool(want_categorize)
    if not (want_tag_translated_b or want_annotate_b or want_categorize_b):
        return False

    claimed = await try_claim_pipeline_followup_once(correlation_id=correlation_id, document_id=document_id)
    if not claimed:
        return False

    db_committed = False
    parsed_started_by = UUID(started_by_id) if started_by_id else None
    started_by = str(parsed_started_by) if parsed_started_by else None
    doc_uuid = UUID(document_id)
    locks_acquired: list[str] = []

    try:
        async with AsyncSessionLocal() as db:
            doc_row = await db.scalar(select(Document.id).where(Document.id == doc_uuid))
            if doc_row is None:
                return False

            if want_tag_translated_b:
                tag_ready = await filter_out_active_jobs(
                    db,
                    [document_id],
                    JobType.TAG,
                    queue_job_key_like="tagger-translated:%",
                )
                if document_id not in tag_ready:
                    return False

            if want_annotate_b:
                ann_ready = await filter_out_active_jobs(db, [document_id], JobType.SUMMARY)
                if document_id not in ann_ready:
                    return False

            if want_categorize_b:
                cat_ready = await filter_out_active_jobs(db, [document_id], JobType.CATEGORIZE)
                if document_id not in cat_ready:
                    return False

            if want_tag_translated_b:
                tag_lock = await try_acquire_enqueue_lock(
                    "tagger_translated",
                    document_id,
                    ttl_sec=settings.saq_tagger_job_timeout_sec + 300,
                )
                if not tag_lock:
                    return False
                locks_acquired.append("tagger_translated")

            if want_annotate_b:
                ann_lock = await try_acquire_enqueue_lock(
                    "annotate",
                    document_id,
                    ttl_sec=settings.saq_annotate_job_timeout_sec + 300,
                )
                if not ann_lock:
                    for k in reversed(locks_acquired):
                        await release_enqueue_lock(k, document_id)
                    return False
                locks_acquired.append("annotate")

            if want_categorize_b:
                cat_lock = await try_acquire_enqueue_lock(
                    "categorize",
                    document_id,
                    ttl_sec=settings.saq_categorize_job_timeout_sec + 300,
                )
                if not cat_lock:
                    for k in reversed(locks_acquired):
                        await release_enqueue_lock(k, document_id)
                    return False
                locks_acquired.append("categorize")

            tag_batch = str(uuid.uuid4()) if want_tag_translated_b else ""
            ann_batch = str(uuid.uuid4()) if want_annotate_b else ""
            cat_batch = str(uuid.uuid4()) if want_categorize_b else ""
            if want_tag_translated_b:
                await init_processing_batch("tagger", tag_batch, scanned=1)
            if want_annotate_b:
                await init_processing_batch("annotate", ann_batch, scanned=1)
            if want_categorize_b:
                await init_processing_batch("categorize", cat_batch, scanned=1)

            tag_queue = get_saq_tagger_queue() if want_tag_translated_b else None
            ann_queue = get_saq_annotate_queue() if want_annotate_b else None
            cat_queue = get_saq_categorize_queue() if want_categorize_b else None
            tag_pj = ann_pj = cat_pj = None
            tag_key = ""
            ann_key = ""
            cat_key = ""

            if want_tag_translated_b and tag_queue is not None:
                await tag_queue.connect()
                tag_key = f"tagger-translated:{tag_batch}:{document_id}"
                tag_pj = ProcessingJob(
                    document_id=doc_uuid,
                    job_type=JobType.TAG,
                    status=JobStatus.PENDING,
                    model_name=settings.model_tagging,
                    provider=provider_label_for_task(LLMTask.TAGGING),
                    batch_id=tag_batch,
                    queue_name=tag_queue.name,
                    queue_job_key=tag_key,
                    started_by_id=parsed_started_by,
                )
                db.add(tag_pj)
                await db.flush()

            if want_annotate_b and ann_queue is not None:
                await ann_queue.connect()
                ann_key = f"annotate:{ann_batch}:{document_id}"
                ann_pj = ProcessingJob(
                    document_id=doc_uuid,
                    job_type=JobType.SUMMARY,
                    status=JobStatus.PENDING,
                    model_name=settings.model_summary,
                    provider=provider_label_for_task(LLMTask.SUMMARY),
                    batch_id=ann_batch,
                    queue_name=ann_queue.name,
                    queue_job_key=ann_key,
                    started_by_id=parsed_started_by,
                )
                db.add(ann_pj)
                await db.flush()

            if want_categorize_b and cat_queue is not None:
                await cat_queue.connect()
                cat_key = f"categorize:{cat_batch}:{document_id}"
                cat_pj = ProcessingJob(
                    document_id=doc_uuid,
                    job_type=JobType.CATEGORIZE,
                    status=JobStatus.PENDING,
                    model_name=settings.model_categorization,
                    provider=provider_label_for_task(LLMTask.CATEGORIZATION),
                    batch_id=cat_batch,
                    queue_name=cat_queue.name,
                    queue_job_key=cat_key,
                    started_by_id=parsed_started_by,
                )
                db.add(cat_pj)
                await db.flush()

            await db.commit()
            db_committed = True

            any_saq_ok = False
            try:
                if want_tag_translated_b and tag_queue is not None and tag_pj is not None:
                    tag_job = await tag_queue.enqueue(
                        "tagger_document_job",
                        key=tag_key,
                        document_id=document_id,
                        use_translation=True,
                        max_tags=max_tags,
                        started_by_id=started_by,
                        batch_id=tag_batch,
                        processing_job_id=str(tag_pj.id),
                        timeout=settings.saq_tagger_job_timeout_sec,
                    )
                    if tag_job is None:
                        row = await db.get(ProcessingJob, tag_pj.id)
                        if row is not None:
                            row.status = JobStatus.CANCELLED
                            row.finished_at = datetime.now(UTC)
                            await db.commit()
                    else:
                        any_saq_ok = True
                        await inc_processing_batch("tagger", tag_batch, "enqueued")

                if want_annotate_b and ann_queue is not None and ann_pj is not None:
                    ann_job = await ann_queue.enqueue(
                        "annotate_document_job",
                        key=ann_key,
                        document_id=document_id,
                        started_by_id=started_by,
                        batch_id=ann_batch,
                        processing_job_id=str(ann_pj.id),
                        timeout=settings.saq_annotate_job_timeout_sec,
                    )
                    if ann_job is None:
                        row = await db.get(ProcessingJob, ann_pj.id)
                        if row is not None:
                            row.status = JobStatus.CANCELLED
                            row.finished_at = datetime.now(UTC)
                            await db.commit()
                    else:
                        any_saq_ok = True
                        await inc_processing_batch("annotate", ann_batch, "enqueued")

                if want_categorize_b and cat_queue is not None and cat_pj is not None:
                    cat_job = await cat_queue.enqueue(
                        "categorize_document_job",
                        key=cat_key,
                        document_id=document_id,
                        started_by_id=started_by,
                        batch_id=cat_batch,
                        processing_job_id=str(cat_pj.id),
                        timeout=settings.saq_categorize_job_timeout_sec,
                    )
                    if cat_job is None:
                        row = await db.get(ProcessingJob, cat_pj.id)
                        if row is not None:
                            row.status = JobStatus.CANCELLED
                            row.finished_at = datetime.now(UTC)
                            await db.commit()
                    else:
                        any_saq_ok = True
                        await inc_processing_batch("categorize", cat_batch, "enqueued")

            finally:
                if tag_queue is not None:
                    await tag_queue.disconnect()
                if ann_queue is not None:
                    await ann_queue.disconnect()
                if cat_queue is not None:
                    await cat_queue.disconnect()

            if db_committed and not any_saq_ok:
                await release_pipeline_followup_claim(correlation_id=correlation_id, document_id=document_id)
                return False
            return any_saq_ok
    finally:
        if claimed and not db_committed:
            await release_pipeline_followup_claim(correlation_id=correlation_id, document_id=document_id)
