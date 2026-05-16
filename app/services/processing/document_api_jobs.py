"""Ручные API-джобы документов: спецификация, фабрики, sync/stream lifecycle."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.db.models import ProcessingJob
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.processing.jobs import (
    MANUAL_API_QUEUE_NAME,
    JobStatus,
    JobType,
    apply_job_timing,
    create_running_job,
    manual_api_queue_job_key,
    processing_job,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DocumentJobSpec:
    document_id: uuid.UUID
    job_type: str
    model_name: str | None
    started_by_id: uuid.UUID | None
    llm_task: LLMTask
    stream: bool = False

    @property
    def queue_job_key(self) -> str:
        suffix = "stream" if self.stream else ""
        return manual_api_queue_job_key(self.job_type, self.document_id, suffix=suffix)


def manual_translate_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
    *,
    stream: bool = False,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.TRANSLATE,
        model_name=settings.model_translation,
        started_by_id=started_by_id,
        llm_task=LLMTask.TRANSLATION,
        stream=stream,
    )


def manual_translate_title_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.TRANSLATE_TITLE,
        model_name=settings.model_translation,
        started_by_id=started_by_id,
        llm_task=LLMTask.TRANSLATION,
    )


def manual_summary_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
    *,
    stream: bool = False,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.SUMMARY,
        model_name=settings.model_summary,
        started_by_id=started_by_id,
        llm_task=LLMTask.SUMMARY,
        stream=stream,
    )


def manual_summary_refine_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
    *,
    stream: bool = False,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.SUMMARY_REFINE,
        model_name=settings.model_summary_refine,
        started_by_id=started_by_id,
        llm_task=LLMTask.SUMMARY_REFINE,
        stream=stream,
    )


def manual_tag_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.TAG,
        model_name=settings.model_tagging,
        started_by_id=started_by_id,
        llm_task=LLMTask.TAGGING,
    )


def manual_categorize_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.CATEGORIZE,
        model_name=settings.model_categorization,
        started_by_id=started_by_id,
        llm_task=LLMTask.CATEGORIZATION,
    )


def manual_entity_extract_spec(
    document_id: uuid.UUID,
    started_by_id: uuid.UUID | None,
) -> DocumentJobSpec:
    return DocumentJobSpec(
        document_id=document_id,
        job_type=JobType.ENTITY_EXTRACT,
        model_name=settings.model_entity_extraction,
        started_by_id=started_by_id,
        llm_task=LLMTask.ENTITY_EXTRACTION,
    )


@dataclass(slots=True)
class ManualStreamJobControl:
    job_id: uuid.UUID
    _t0: float
    _failed: bool = False
    _cancelled: bool = False
    _error_message: str | None = None

    def mark_failed(self, message: str) -> None:
        self._failed = True
        self._error_message = message[:20000]

    def mark_cancelled(self) -> None:
        self._cancelled = True


async def run_tracked_document_work(
    session: AsyncSession,
    *,
    spec: DocumentJobSpec,
    track_job: bool,
    work: Callable[[], Awaitable[T]],
) -> T:
    if not track_job:
        return await work()
    async with manual_api_job_session(session, spec):
        return await work()


@asynccontextmanager
async def manual_api_job_session(session: AsyncSession, spec: DocumentJobSpec):
    async with processing_job(
        session,
        document_id=spec.document_id,
        job_type=spec.job_type,
        model_name=spec.model_name,
        provider=None,
        started_by_id=spec.started_by_id,
        llm_task_for_provider=spec.llm_task,
        queue_name=MANUAL_API_QUEUE_NAME,
        queue_job_key=spec.queue_job_key,
    ) as job:
        yield job


@asynccontextmanager
async def manual_api_stream_job(spec: DocumentJobSpec):
    """Отдельная сессия: таймер от старта стрима до persist, ошибки или отмены клиента."""
    t0 = time.perf_counter()
    job_id = await _insert_running_manual_job(spec)
    ctl = ManualStreamJobControl(job_id=job_id, _t0=t0)
    try:
        yield ctl
    except asyncio.CancelledError:
        ctl.mark_cancelled()
        raise
    finally:
        await _finalize_manual_job(
            ctl.job_id,
            t0=ctl._t0,
            failed=ctl._failed,
            cancelled=ctl._cancelled,
            error_message=ctl._error_message,
        )


async def _insert_running_manual_job(spec: DocumentJobSpec) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            job = create_running_job(
                document_id=spec.document_id,
                job_type=spec.job_type,
                model_name=spec.model_name,
                started_by_id=spec.started_by_id,
                llm_task_for_provider=spec.llm_task,
                queue_name=MANUAL_API_QUEUE_NAME,
                queue_job_key=spec.queue_job_key,
            )
            session.add(job)
            await session.flush()
            return job.id


async def _finalize_manual_job(
    job_id: uuid.UUID,
    *,
    t0: float,
    failed: bool,
    cancelled: bool,
    error_message: str | None,
) -> None:
    if cancelled:
        status = JobStatus.CANCELLED
    elif failed:
        status = JobStatus.FAILED
    else:
        status = JobStatus.COMPLETED

    async with AsyncSessionLocal() as session:
        async with session.begin():
            job = await session.get(ProcessingJob, job_id)
            if job is None:
                return
            job.status = status
            if failed and error_message:
                job.error_message = error_message
            apply_job_timing(job, t0=t0)
