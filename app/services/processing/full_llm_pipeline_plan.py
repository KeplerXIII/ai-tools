"""Какие шаги full LLM pipeline ещё нужны по состоянию документа в БД (без учёта активных джобов)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Document, DocumentCategory, DocumentEntity, DocumentTag, Tag
from app.services.documents.db_refs import language_id_by_code


@dataclass(frozen=True, slots=True)
class FullLlmPipelinePlanEntry:
    # need_translate: тело ещё не на target_lang
    need_translate: bool
    # need_translate_title: тело уже на target_lang, заголовок не переведён
    need_translate_title: bool
    need_tag_original: bool
    need_extractor: bool
    need_phase_b: bool


def is_pipeline_document_blocked_for_phase_a(
    plan: FullLlmPipelinePlanEntry,
    document_id: str,
    *,
    translate_free: set[str],
    tag_original_free: set[str],
    extractor_free: set[str],
) -> bool:
    """Если для нужного шага фазы A уже есть активный джоб — документ в этот проход не берём (целиком)."""
    if (plan.need_translate or plan.need_translate_title) and document_id not in translate_free:
        return True
    if plan.need_tag_original and document_id not in tag_original_free:
        return True
    if plan.need_extractor and document_id not in extractor_free:
        return True
    return False


async def map_document_pipeline_plans(
    session: AsyncSession,
    *,
    document_ids: list[str],
    target_lang: str,
) -> dict[str, FullLlmPipelinePlanEntry]:
    if not document_ids:
        return {}
    uuids = [UUID(d) for d in document_ids]
    target_lang_id = await language_id_by_code(session, target_lang)

    docs = (await session.scalars(select(Document).where(Document.id.in_(uuids)))).all()
    by_id: dict[str, Document] = {str(d.id): d for d in docs}

    # Документы с хотя бы одним тегом на языке оригинала
    q_orig_tags = (
        select(DocumentTag.document_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .join(Document, Document.id == DocumentTag.document_id)
        .where(
            DocumentTag.document_id.in_(uuids),
            Tag.language_id == Document.original_language_id,
        )
        .distinct()
    )
    with_orig_tags = set(str(x) for x in (await session.scalars(q_orig_tags)).all())

    q_entities = select(DocumentEntity.document_id).where(DocumentEntity.document_id.in_(uuids)).distinct()
    with_entities = set(str(x) for x in (await session.scalars(q_entities)).all())

    q_tr_tags = (
        select(DocumentTag.document_id)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .join(Document, Document.id == DocumentTag.document_id)
        .where(
            DocumentTag.document_id.in_(uuids),
            Document.translated_language_id.is_not(None),
            Tag.language_id == Document.translated_language_id,
        )
        .distinct()
    )
    with_translated_tags = set(str(x) for x in (await session.scalars(q_tr_tags)).all())

    q_cat = select(DocumentCategory.document_id).where(DocumentCategory.document_id.in_(uuids)).distinct()
    with_categories = set(str(x) for x in (await session.scalars(q_cat)).all())

    out: dict[str, FullLlmPipelinePlanEntry] = {}
    for did in document_ids:
        doc = by_id.get(did)
        if doc is None:
            continue
        orig_text = (doc.original_content or "").strip()
        has_target_translation = (
            bool((doc.translated_content or "").strip())
            and doc.translated_language_id is not None
            and doc.translated_language_id == target_lang_id
        )
        need_translate = bool(orig_text) and not has_target_translation
        need_translate_title = (
            has_target_translation
            and bool((doc.title or "").strip())
            and not bool((doc.translated_title or "").strip())
        )
        need_tag_original = bool(orig_text) and did not in with_orig_tags
        need_extractor = bool(orig_text) and did not in with_entities

        has_annotation = bool((doc.translated_summary or "").strip())
        need_b_tag = has_target_translation and did not in with_translated_tags
        need_b_ann = has_target_translation and (not has_annotation or bool(doc.translated_summary_stale))
        need_b_cat = has_target_translation and did not in with_categories
        need_phase_b = need_b_tag or need_b_ann or need_b_cat

        out[did] = FullLlmPipelinePlanEntry(
            need_translate=need_translate,
            need_translate_title=need_translate_title,
            need_tag_original=need_tag_original,
            need_extractor=need_extractor,
            need_phase_b=need_phase_b,
        )
    return out
