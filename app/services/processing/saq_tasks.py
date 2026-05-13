from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from time import perf_counter

from collections.abc import Mapping

from app.core.config import settings
from app.domain.errors import ValidationError
from app.infrastructure.db.models import ProcessingJob, SourceParseRun
from app.infrastructure.db.session import AsyncSessionLocal
from app.schemas.documents import SummarySource
from app.services.processing.post_parse_llm_dispatch import dispatch_post_parse_llm_jobs
from app.services.documents.document_pipeline import (
    run_categorize_document,
    run_entity_extract_document,
    run_summary_document,
    run_tag_document,
    run_translate_document,
)
from app.services.parsing.parse_source_runner import execute_parse_source
from app.services.processing.jobs import JobStatus
from app.services.processing.pipeline_followup import schedule_post_translate_pipeline_jobs
from app.services.processing.redis_batch_store import inc_processing_batch
from app.services.processing.saq_job_runner import run_tracked_document_job

_log = logging.getLogger(__name__)


def _post_parse_options_as_dict(raw: object) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, Mapping):
        return dict(raw)
    return None


async def translate_document_job(
    ctx: dict,
    *,
    document_id: str,
    target_lang: str = "ru",
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
    pipeline_correlation_id: str | None = None,
    pipeline_max_tags: int = 10,
    pipeline_followup_tag_translated: bool = True,
    pipeline_followup_annotate: bool = True,
    pipeline_followup_categorize: bool = True,
) -> dict[str, str]:
    async def work(session, doc_id, started_by, pj):
        await run_translate_document(
            session,
            document_id=doc_id,
            target_lang=target_lang,
            started_by_id=started_by,
            track_job=pj is None,
        )

    result = await run_tracked_document_job(
        document_id=document_id,
        started_by_id=started_by_id,
        batch_id=batch_id,
        processing_job_id=processing_job_id,
        lock_kind="translate",
        on_batch_inc=lambda bid, field: inc_processing_batch("translate", bid, field),
        success_status="translated",
        work=work,
    )
    wants_followup = (
        pipeline_followup_tag_translated
        or pipeline_followup_annotate
        or pipeline_followup_categorize
    )
    if (
        result.get("status") == "translated"
        and pipeline_correlation_id
        and wants_followup
    ):
        try:
            await schedule_post_translate_pipeline_jobs(
                document_id=document_id,
                correlation_id=pipeline_correlation_id,
                max_tags=pipeline_max_tags,
                started_by_id=started_by_id,
                want_tag_translated=pipeline_followup_tag_translated,
                want_annotate=pipeline_followup_annotate,
                want_categorize=pipeline_followup_categorize,
            )
        except Exception:
            _log.exception(
                "pipeline follow-up enqueue failed document_id=%s correlation_id=%s",
                document_id,
                pipeline_correlation_id,
            )
    return result


async def annotate_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    async def work(session, doc_id, started_by, pj):
        await run_summary_document(
            session,
            document_id=doc_id,
            source=SummarySource.translated,
            started_by_id=started_by,
            track_job=pj is None,
        )

    return await run_tracked_document_job(
        document_id=document_id,
        started_by_id=started_by_id,
        batch_id=batch_id,
        processing_job_id=processing_job_id,
        lock_kind="annotate",
        on_batch_inc=lambda bid, field: inc_processing_batch("annotate", bid, field),
        success_status="annotated",
        work=work,
    )


async def categorize_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    async def work(session, doc_id, started_by, pj):
        await run_categorize_document(
            session,
            document_id=doc_id,
            started_by_id=started_by,
            track_job=pj is None,
        )

    return await run_tracked_document_job(
        document_id=document_id,
        started_by_id=started_by_id,
        batch_id=batch_id,
        processing_job_id=processing_job_id,
        lock_kind="categorize",
        on_batch_inc=lambda bid, field: inc_processing_batch("categorize", bid, field),
        success_status="categorized",
        work=work,
    )


async def extractor_document_job(
    ctx: dict,
    *,
    document_id: str,
    started_by_id: str | None = None,
    batch_id: str | None = None,
    processing_job_id: str | None = None,
) -> dict[str, str]:
    async def work(session, doc_id, started_by, pj):
        await run_entity_extract_document(
            session,
            document_id=doc_id,
            started_by_id=started_by,
            track_job=pj is None,
        )

    return await run_tracked_document_job(
        document_id=document_id,
        started_by_id=started_by_id,
        batch_id=batch_id,
        processing_job_id=processing_job_id,
        lock_kind="extractor",
        on_batch_inc=lambda bid, field: inc_processing_batch("extractor", bid, field),
        success_status="extracted",
        work=work,
    )


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
    lock_kind = "tagger_translated" if use_translation else "tagger_original"
    mode = "translated" if use_translation else "original"

    async def work(session, doc_id, started_by, pj):
        await run_tag_document(
            session,
            document_id=doc_id,
            max_tags=max_tags,
            use_translation=use_translation,
            started_by_id=started_by,
            track_job=pj is None,
        )

    return await run_tracked_document_job(
        document_id=document_id,
        started_by_id=started_by_id,
        batch_id=batch_id,
        processing_job_id=processing_job_id,
        lock_kind=lock_kind,
        on_batch_inc=lambda bid, field: inc_processing_batch("tagger", bid, field),
        success_status=f"tagged_{mode}",
        work=work,
    )


async def parse_source_job(ctx: dict, *, parse_run_id: str) -> dict[str, str]:
    parsed_id = uuid.UUID(parse_run_id)
    t0 = perf_counter()
    async with AsyncSessionLocal() as session:
        run = await session.get(SourceParseRun, parsed_id)
        if run is None:
            return {"parse_run_id": parse_run_id, "status": "missing"}

        now = datetime.now(UTC)
        # Воркер мог умереть после commit в running; повторная доставка SAQ раньше сразу
        # делала return "skipped" и оставляла processing_jobs в running навсегда.
        if run.status == "running":
            started = run.started_at
            limit = timedelta(seconds=settings.saq_parse_job_timeout_sec + 300)
            if started is None:
                stale = True
            else:
                aware = started if started.tzinfo else started.replace(tzinfo=UTC)
                aware = aware.astimezone(UTC)
                stale = (now - aware) > limit
            if stale:
                msg = (
                    "Прервано (таймаут или остановка воркера). Запустите разбор источника снова."
                )
                run.status = "failed"
                run.finished_at = now
                run.phase = "failed"
                run.error_message = msg
                pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
                if pj is not None and pj.status in (JobStatus.PENDING, JobStatus.RUNNING):
                    pj.status = JobStatus.FAILED
                    pj.finished_at = now
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                    pj.error_message = msg
                await session.commit()
                return {"parse_run_id": parse_run_id, "status": "failed"}

        if run.status != "pending":
            pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
            if pj is not None and pj.status == JobStatus.RUNNING and run.status in ("completed", "failed"):
                if run.status == "completed":
                    pj.status = JobStatus.COMPLETED
                    pj.finished_at = run.finished_at or now
                else:
                    pj.status = JobStatus.FAILED
                    pj.finished_at = run.finished_at or now
                    pj.error_message = run.error_message
                await session.commit()
            return {"parse_run_id": parse_run_id, "status": "skipped"}

        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.phase = "discovery"
        pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
        if pj is not None and pj.status == JobStatus.PENDING:
            pj.status = JobStatus.RUNNING
            pj.started_at = datetime.now(UTC)
        await session.commit()

        try:
            outcome = await execute_parse_source(
                session,
                source_id=run.source_id,
                days=run.days,
                skip_undated=run.skip_undated,
                created_by_id=run.created_by_id,
                parse_run_id=parsed_id,
            )
            run = await session.get(SourceParseRun, parsed_id)
            if run is None:
                return {"parse_run_id": parse_run_id, "status": "missing"}
            run.status = "completed"
            run.finished_at = datetime.now(UTC)
            run.found_total = outcome.found_total
            run.created_total = outcome.created_total
            run.new_document_ids = [str(x) for x in outcome.new_document_ids]
            run.phase = "complete"
            pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
            if pj is not None:
                pj.status = JobStatus.COMPLETED
                pj.finished_at = datetime.now(UTC)
                pj.duration_ms = int((perf_counter() - t0) * 1000)
            # До commit: иначе после expire объекта run доступ к полям даёт слабую загрузку.
            raw_post_parse = run.post_parse_options
            pipeline_started_by_id = run.created_by_id
            await session.commit()

            opts = _post_parse_options_as_dict(raw_post_parse)

            if not opts:
                _log.info(
                    "post-parse LLM skipped parse_run_id=%s (no post_parse options)",
                    parse_run_id,
                )
            elif not outcome.new_document_ids:
                _log.info(
                    "post-parse LLM skipped parse_run_id=%s (no new documents)",
                    parse_run_id,
                )
            else:
                try:
                    async with AsyncSessionLocal() as pipeline_session:
                        summary = await dispatch_post_parse_llm_jobs(
                            pipeline_session,
                            document_ids=list(outcome.new_document_ids),
                            started_by_id=pipeline_started_by_id,
                            opts=opts,
                        )
                    _log.info(
                        "post-parse LLM parse_run_id=%s documents=%s summary=%s",
                        parse_run_id,
                        len(outcome.new_document_ids),
                        summary,
                    )
                except Exception:
                    _log.exception(
                        "post-parse LLM dispatch failed parse_run_id=%s",
                        parse_run_id,
                    )

            return {"parse_run_id": parse_run_id, "status": "completed"}
        except ValidationError as exc:
            await session.rollback()
            run = await session.get(SourceParseRun, parsed_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.error_message = str(exc)[:8000]
                run.phase = "failed"
                pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
                if pj is not None:
                    pj.status = JobStatus.FAILED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                    pj.error_message = str(exc)[:8000]
                await session.commit()
            return {"parse_run_id": parse_run_id, "status": "failed"}
        except Exception as exc:
            await session.rollback()
            run = await session.get(SourceParseRun, parsed_id)
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                run.error_message = str(exc)[:8000]
                run.phase = "failed"
                pj = await session.get(ProcessingJob, run.processing_job_id) if run.processing_job_id else None
                if pj is not None:
                    pj.status = JobStatus.FAILED
                    pj.finished_at = datetime.now(UTC)
                    pj.duration_ms = int((perf_counter() - t0) * 1000)
                    pj.error_message = str(exc)[:8000]
                await session.commit()
            return {"parse_run_id": parse_run_id, "status": "failed"}
