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
) -> AsyncGenerator[ProcessingJob, None]:
    job = ProcessingJob(
        document_id=document_id,
        job_type=job_type,
        status=JobStatus.RUNNING,
        model_name=model_name,
        provider=provider
        or (
            _provider_for_llm_task(llm_task_for_provider)
            if llm_task_for_provider
            else provider_label_default()
        ),
        started_by_id=started_by_id,
        started_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    t0 = time.perf_counter()
    try:
        async with session.begin_nested():
            yield job
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        job.duration_ms = int((time.perf_counter() - t0) * 1000)
        job.error_message = str(exc)[:20000]
        raise
    job.status = JobStatus.COMPLETED
    job.finished_at = datetime.now(UTC)
    job.duration_ms = int((time.perf_counter() - t0) * 1000)
