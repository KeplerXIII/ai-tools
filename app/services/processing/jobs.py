from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.llm_task import LLMTask
from app.infrastructure.db.models import ProcessingJob


class JobType:
    PARSE_SOURCE = "parse_source"
    EXTRACT = "extract"
    TRANSLATE = "translate"
    TRANSLATE_TITLE = "translate_title"
    SUMMARY = "summary"
    SUMMARY_REFINE = "summary_refine"
    TAG = "tag"
    ENTITY_EXTRACT = "entity_extract"
    CATEGORIZE = "categorize"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    OCR = "ocr"


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Синхронные вызовы API (не SAQ): видно в мониторинге в queue_name.
MANUAL_API_QUEUE_NAME = "api-manual"


def manual_api_queue_job_key(job_type: str, document_id: uuid.UUID, *, suffix: str = "") -> str:
    key = f"manual:{job_type}:{document_id}"
    return f"{key}:{suffix}" if suffix else key


def _provider_for_llm_task(task: LLMTask) -> str:
    from urllib.parse import urlparse

    ep = settings.openai_endpoint_for(task)
    return urlparse(ep.base_url).netloc or "llm"


def provider_label_default() -> str:
    return _provider_for_llm_task(LLMTask.SUMMARY)


def provider_label_for_task(task: LLMTask) -> str:
    return _provider_for_llm_task(task)


def provider_label_embedding() -> str:
    from urllib.parse import urlparse

    return urlparse(settings.embedding_tei_base_url).netloc or "tei"


def _resolve_provider(
    provider: str | None,
    llm_task_for_provider: LLMTask | None,
) -> str:
    if provider:
        return provider
    if llm_task_for_provider:
        return _provider_for_llm_task(llm_task_for_provider)
    return provider_label_default()


def create_running_job(
    *,
    document_id: uuid.UUID,
    job_type: str,
    model_name: str | None,
    started_by_id: uuid.UUID | None,
    llm_task_for_provider: LLMTask | None = None,
    provider: str | None = None,
    queue_name: str | None = None,
    queue_job_key: str | None = None,
    batch_id: str | None = None,
) -> ProcessingJob:
    return ProcessingJob(
        document_id=document_id,
        job_type=job_type,
        status=JobStatus.RUNNING,
        model_name=model_name,
        provider=_resolve_provider(provider, llm_task_for_provider),
        batch_id=batch_id,
        queue_name=queue_name,
        queue_job_key=queue_job_key,
        started_by_id=started_by_id,
        started_at=datetime.now(UTC),
    )


def apply_job_timing(job: ProcessingJob, *, t0: float) -> None:
    job.finished_at = datetime.now(UTC)
    job.duration_ms = int((time.perf_counter() - t0) * 1000)


@asynccontextmanager
async def processing_job(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    job_type: str,
    model_name: str | None,
    provider: str | None,
    started_by_id: uuid.UUID | None,
    llm_task_for_provider: LLMTask | None = None,
    queue_name: str | None = None,
    queue_job_key: str | None = None,
    batch_id: str | None = None,
) -> AsyncGenerator[ProcessingJob, None]:
    job = create_running_job(
        document_id=document_id,
        job_type=job_type,
        model_name=model_name,
        started_by_id=started_by_id,
        llm_task_for_provider=llm_task_for_provider,
        provider=provider,
        queue_name=queue_name,
        queue_job_key=queue_job_key,
        batch_id=batch_id,
    )
    session.add(job)
    await session.flush()
    t0 = time.perf_counter()
    try:
        async with session.begin_nested():
            yield job
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error_message = str(exc)[:20000]
        apply_job_timing(job, t0=t0)
        raise
    job.status = JobStatus.COMPLETED
    apply_job_timing(job, t0=t0)
