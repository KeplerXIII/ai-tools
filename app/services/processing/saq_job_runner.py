from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFoundError
from app.infrastructure.db.models import ProcessingJob
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.processing.enqueue_locks import release_enqueue_lock
from app.services.processing.jobs import JobStatus

_FK_PROCESSING_JOBS_DOCUMENT = "processing_jobs_document_id_fkey"

DocumentWork = Callable[
    [AsyncSession, uuid.UUID, uuid.UUID | None, ProcessingJob | None],
    Awaitable[None],
]


async def run_tracked_document_job(
    *,
    document_id: str,
    started_by_id: str | None,
    batch_id: str | None,
    processing_job_id: str | None,
    lock_kind: str,
    on_batch_inc: Callable[[str, str], Awaitable[None]] | None,
    success_status: str,
    work: DocumentWork,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None
    parsed_processing_job_id = uuid.UUID(processing_job_id) if processing_job_id else None

    async def bump(field: str) -> None:
        if batch_id and on_batch_inc:
            await on_batch_inc(batch_id, field)

    try:
        async with AsyncSessionLocal() as session:
            pj: ProcessingJob | None = None
            t0 = perf_counter()
            if parsed_processing_job_id:
                pj = await session.get(ProcessingJob, parsed_processing_job_id)
                if pj is not None and pj.status == JobStatus.PENDING:
                    pj.status = JobStatus.RUNNING
                    pj.started_at = datetime.now(UTC)
                    await session.commit()
            try:
                await work(session, parsed_document_id, parsed_started_by, pj)
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
                await bump("skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            except IntegrityError as exc:
                await session.rollback()
                if parsed_processing_job_id and _FK_PROCESSING_JOBS_DOCUMENT in str(exc):
                    fallback = await session.get(ProcessingJob, parsed_processing_job_id)
                    if fallback is not None:
                        fallback.status = JobStatus.CANCELLED
                        fallback.finished_at = datetime.now(UTC)
                        await session.commit()
                if _FK_PROCESSING_JOBS_DOCUMENT in str(exc):
                    await bump("skipped")
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
                await bump("failed")
                raise

        await bump("completed")
        return {
            "document_id": document_id,
            "status": success_status,
        }
    finally:
        await release_enqueue_lock(lock_kind, document_id)
