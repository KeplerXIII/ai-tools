"""SSE-стрим ручных API-джобов документов (translate / summary / refine)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

from app.api.streaming_utils import (
    coop_text_chunks,
    sse_data_event_bytes,
    sse_error_event_bytes,
)
from app.services.processing.document_api_jobs import (
    DocumentJobSpec,
    manual_api_stream_job,
)

logger = logging.getLogger(__name__)

LlmStreamFactory = Callable[[], Awaitable[AsyncIterator[str]]]
PersistCallback = Callable[[str], Awaitable[None]]


async def stream_manual_api_llm(
    spec: DocumentJobSpec,
    *,
    llm_stream_factory: LlmStreamFactory,
    persist: PersistCallback,
) -> AsyncIterator[bytes]:
    async with manual_api_stream_job(spec) as job:
        try:
            try:
                stream = await llm_stream_factory()
            except Exception as exc:
                job.mark_failed(str(exc))
                yield sse_error_event_bytes(f"[stream_error] {exc}")
                return

            parts: list[str] = []
            try:
                async for chunk in coop_text_chunks(stream):
                    parts.append(chunk)
                    yield sse_data_event_bytes(chunk)
            except Exception as exc:
                job.mark_failed(str(exc))
                yield sse_error_event_bytes(f"[stream_error] {exc}")
                return

            try:
                await persist("".join(parts))
            except Exception as exc:
                job.mark_failed(str(exc))
                logger.exception(
                    "persist after manual API stream failed document_id=%s job_type=%s",
                    spec.document_id,
                    spec.job_type,
                )
                yield sse_error_event_bytes(f"[persist_error] {exc}")
                return

            yield sse_data_event_bytes("[DONE]")
        except asyncio.CancelledError:
            job.mark_cancelled()
            raise
