"""Общие запросы для постановки processing-джобов (API и пайплайны)."""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Document, ProcessingJob
from app.services.processing.jobs import JobStatus, JobType


def dedupe_document_ids_preserve_order(document_ids: list[UUID]) -> list[UUID]:
    return list(dict.fromkeys(document_ids))


async def require_documents_exist(db: AsyncSession, document_ids: list[UUID]) -> list[str]:
    ordered = dedupe_document_ids_preserve_order(document_ids)
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


async def filter_out_active_jobs(
    db: AsyncSession,
    document_ids: list[str],
    job_type: str,
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
