from __future__ import annotations

import uuid
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.exc import IntegrityError

from app.domain.errors import NotFoundError
from app.infrastructure.db.models import ProcessingJob
from app.infrastructure.db.session import AsyncSessionLocal
from app.schemas.documents import SummarySource
from app.services.documents.document_pipeline import run_translate_document
from app.services.documents.document_pipeline import run_summary_document
from app.services.documents.document_pipeline import run_categorize_document
from app.services.documents.document_pipeline import run_entity_extract_document
from app.services.documents.document_pipeline import run_tag_document
from app.services.processing.annotate_batch_store import inc_annotate_batch_counter
from app.services.processing.categorize_batch_store import inc_categorize_batch_counter
from app.services.processing.extractor_batch_store import inc_extractor_batch_counter
from app.services.processing.enqueue_locks import release_enqueue_lock
from app.services.processing.jobs import JobStatus
from app.services.processing.tagger_batch_store import inc_tagger_batch_counter
from app.services.processing.translate_batch_store import inc_translate_batch_counter


async def translate_document_job(
    ctx: dict,
    *,
    document_id: str,
    target_lang: str = "ru",
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    # Persist intermediate state so monitoring can observe running jobs.
                    await session.commit()
            try:
                await run_translate_document(
                    session,
                    document_id=parsed_document_id,
                    target_lang=target_lang,
                    started_by_id=parsed_started_by,
                    track_job=pj is None,
                )
                if pj is not None:
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                await session.commit()
            except NotFoundError:
                # The document may be deleted after enqueue and before processing.
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if batch_id:
                    await inc_translate_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                # FK violation on processing_jobs.document_id can happen in delete races.
                await session.rollback()
                if parsed_processing_job_id and "processing_jobs_document_id_fkey" in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if "processing_jobs_document_id_fkey" in str(exc):
                    if batch_id:
                        await inc_translate_batch_counter(batch_id, "skipped")
                    return {
                        "document_id": document_id,
                        "status": "skipped_not_found",
                    }
                raise
            except Exception:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.FAILED
                        fallback.finished_at = datetime.now(UTC)
                        fallback.duration_ms = int((perf_counter() - t0) * 1000)
                        await session.commit()
                if batch_id:
                    await inc_translate_batch_counter(batch_id, "failed")
                raise

        if batch_id:
            await inc_translate_batch_counter(batch_id, "completed")
        return {
            "document_id": document_id,
            "status": "translated",
        }
    finally:
        await release_enqueue_lock("translate", document_id)


async def annotate_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    # Persist intermediate state so monitoring can observe running jobs.
                    await session.commit()
            try:
                await run_summary_document(
                    session,
                    document_id=parsed_document_id,
                    source=SummarySource.translated,
                    started_by_id=parsed_started_by,
                    track_job=pj is None,
                )
                if pj is not None:
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                await session.commit()
            except NotFoundError:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if batch_id:
                    await inc_annotate_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                await session.rollback()
                if parsed_processing_job_id and "processing_jobs_document_id_fkey" in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if "processing_jobs_document_id_fkey" in str(exc):
                    if batch_id:
                        await inc_annotate_batch_counter(batch_id, "skipped")
                    return {
                        "document_id": document_id,
                        "status": "skipped_not_found",
                    }
                raise
            except Exception:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.FAILED
                        fallback.finished_at = datetime.now(UTC)
                        fallback.duration_ms = int((perf_counter() - t0) * 1000)
                        await session.commit()
                if batch_id:
                    await inc_annotate_batch_counter(batch_id, "failed")
                raise

        if batch_id:
            await inc_annotate_batch_counter(batch_id, "completed")
        return {
            "document_id": document_id,
            "status": "annotated",
        }
    finally:
        await release_enqueue_lock("annotate", document_id)


async def categorize_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    # Persist intermediate state so monitoring can observe running jobs.
                    await session.commit()
            try:
                await run_categorize_document(
                    session,
                    document_id=parsed_document_id,
                    started_by_id=parsed_started_by,
                    track_job=pj is None,
                )
                if pj is not None:
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                await session.commit()
            except NotFoundError:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if batch_id:
                    await inc_categorize_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                await session.rollback()
                if parsed_processing_job_id and "processing_jobs_document_id_fkey" in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if "processing_jobs_document_id_fkey" in str(exc):
                    if batch_id:
                        await inc_categorize_batch_counter(batch_id, "skipped")
                    return {
                        "document_id": document_id,
                        "status": "skipped_not_found",
                    }
                raise
            except Exception:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.FAILED
                        fallback.finished_at = datetime.now(UTC)
                        fallback.duration_ms = int((perf_counter() - t0) * 1000)
                        await session.commit()
                if batch_id:
                    await inc_categorize_batch_counter(batch_id, "failed")
                raise

        if batch_id:
            await inc_categorize_batch_counter(batch_id, "completed")
        return {
            "document_id": document_id,
            "status": "categorized",
        }
    finally:
        await release_enqueue_lock("categorize", document_id)


async def extractor_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    # Persist intermediate state so monitoring can observe running jobs.
                    await session.commit()
            try:
                await run_entity_extract_document(
                    session,
                    document_id=parsed_document_id,
                    started_by_id=parsed_started_by,
                    track_job=pj is None,
                )
                if pj is not None:
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                await session.commit()
            except NotFoundError:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if batch_id:
                    await inc_extractor_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                await session.rollback()
                if parsed_processing_job_id and "processing_jobs_document_id_fkey" in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if "processing_jobs_document_id_fkey" in str(exc):
                    if batch_id:
                        await inc_extractor_batch_counter(batch_id, "skipped")
                    return {
                        "document_id": document_id,
                        "status": "skipped_not_found",
                    }
                raise
            except Exception:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.FAILED
                        fallback.finished_at = datetime.now(UTC)
                        fallback.duration_ms = int((perf_counter() - t0) * 1000)
                        await session.commit()
                if batch_id:
                    await inc_extractor_batch_counter(batch_id, "failed")
                raise

        if batch_id:
            await inc_extractor_batch_counter(batch_id, "completed")
        return {
            "document_id": document_id,
            "status": "extracted",
        }
    finally:
        await release_enqueue_lock("extractor", document_id)


async def tagger_document_job(
    ctx: dict,
    *,
    document_id: str,
    use_translation: bool = False,
    max_tags: int = 10,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    lock_kind = "tagger_translated" if use_translation else "tagger_original"
    mode = "translated" if use_translation else "original"

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    # Persist intermediate state so monitoring can observe running jobs.
                    await session.commit()
            try:
                await run_tag_document(
                    session,
                    document_id=parsed_document_id,
                    max_tags=max_tags,
                    use_translation=use_translation,
                    started_by_id=parsed_started_by,
                    track_job=pj is None,
                )
                if pj is not None:
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                await session.commit()
            except NotFoundError:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if batch_id:
                    await inc_tagger_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                await session.rollback()
                if parsed_processing_job_id and "processing_jobs_document_id_fkey" in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if "processing_jobs_document_id_fkey" in str(exc):
                    if batch_id:
                        await inc_tagger_batch_counter(batch_id, "skipped")
                    return {
                        "document_id": document_id,
                        "status": "skipped_not_found",
                    }
                raise
            except Exception:
                await session.rollback()
                if parsed_processing_job_id:
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.FAILED
                        fallback.finished_at = datetime.now(UTC)
                        fallback.duration_ms = int((perf_counter() - t0) * 1000)
                        await session.commit()
                if batch_id:
                    await inc_tagger_batch_counter(batch_id, "failed")
                raise

        if batch_id:
            await inc_tagger_batch_counter(batch_id, "completed")
        return {
            "document_id": document_id,
            "status": f"tagged_{mode}",
        }
    finally:
        await release_enqueue_lock(lock_kind, document_id)
