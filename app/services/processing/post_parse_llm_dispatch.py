"""После разбора источника: полный пайплайн или выбранные типы LLM-задач."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.processing import EnqueueFullLlmPipelineRequest
from app.services.processing.document_stage_enqueue import (
    enqueue_categorize_batch,
    enqueue_extractor_batch,
    enqueue_tagger_batch,
    enqueue_translate_batch,
)
from app.services.processing.full_llm_pipeline_enqueue import enqueue_full_llm_pipeline_core


def _flag(opts: Mapping[str, Any], key: str) -> bool:
    v = opts.get(key)
    if v is True:
        return True
    if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes"):
        return True
    if isinstance(v, (int, float)) and int(v) == 1:
        return True
    return False


async def dispatch_post_parse_llm_jobs(
    db: AsyncSession,
    *,
    document_ids: list[UUID],
    started_by_id: UUID | None,
    opts: Mapping[str, Any],
) -> str:
    """Возвращает краткое сообщение для логов."""
    if not document_ids:
        return "no_documents"
    if _flag(opts, "full_llm_pipeline"):
        req = EnqueueFullLlmPipelineRequest(
            document_ids=document_ids,
            target_lang=str(opts.get("target_lang") or "ru"),
            max_tags=int(opts.get("max_tags") or 10),
        )
        r = await enqueue_full_llm_pipeline_core(db, req, started_by_id=started_by_id)
        return f"full_llm_pipeline enqueued={r.enqueued} scanned={r.scanned}"

    max_tags = int(opts.get("max_tags") or 10)
    target_lang = str(opts.get("target_lang") or "ru")

    want_tag_orig = _flag(opts, "llm_tag_original")
    want_tr = _flag(opts, "llm_translate")
    want_ext = _flag(opts, "llm_extractor")
    want_tag_tr = _flag(opts, "llm_tag_translated")
    want_ann = _flag(opts, "llm_annotate")
    want_cat = _flag(opts, "llm_categorize")

    followup_tag_tr = want_tr and want_tag_tr
    followup_ann = want_tr and want_ann
    followup_cat = want_tr and want_cat
    need_translate_followup_bundle = bool(followup_tag_tr or followup_ann or followup_cat)

    pipeline_correlation_id = (
        str(uuid.uuid4())
        if want_tr and need_translate_followup_bundle
        else None
    )

    parts: list[str] = []

    if want_tag_orig:
        x = await enqueue_tagger_batch(
            db,
            document_ids=document_ids,
            max_tags=max_tags,
            use_translation=False,
            started_by_id=started_by_id,
        )
        parts.append(f"tag_original:{x.enqueued}")

    immediate_cat = want_cat and not want_tr
    if immediate_cat:
        x = await enqueue_categorize_batch(db, document_ids=document_ids, started_by_id=started_by_id)
        parts.append(f"categorize_immediate:{x.enqueued}")

    if want_ext:
        x = await enqueue_extractor_batch(db, document_ids=document_ids, started_by_id=started_by_id)
        parts.append(f"extractor:{x.enqueued}")

    if want_tr:
        x = await enqueue_translate_batch(
            db,
            document_ids=document_ids,
            target_lang=target_lang,
            started_by_id=started_by_id,
            pipeline_correlation_id=pipeline_correlation_id,
            pipeline_max_tags=max_tags,
            pipeline_followup_tag_translated=followup_tag_tr,
            pipeline_followup_annotate=followup_ann,
            pipeline_followup_categorize=followup_cat,
        )
        suf = ""
        if pipeline_correlation_id:
            suf = f" defer=[tag_tr:{followup_tag_tr},ann:{followup_ann},cat:{followup_cat}]"
        parts.append(f"translate:{x.enqueued}{suf}")

    if want_tag_tr and not want_tr:
        parts.append("skipped:tag_translated_requires_translate")
    if want_ann and not want_tr:
        parts.append("skipped:annotate_requires_translate")
    if want_cat and want_tr:
        parts.append("categorize_deferred_after_translate")

    if not parts:
        return "no_llm_flags"
    return " ".join(parts)
