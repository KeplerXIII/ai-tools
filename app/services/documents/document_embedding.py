"""Инкрементальная векторизация документов (fp → TEI → pgvector)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.errors import ExternalServiceError, NotFoundError
from app.infrastructure.db.models import Document, DocumentChunk, DocumentEmbedding, EmbeddingModel
from app.infrastructure.db.session import AsyncSessionLocal
from app.infrastructure.llm.clients.embedding_client import create_embeddings
from app.services.documents.db_refs import language_id_by_code

_log = logging.getLogger(__name__)

_model_id_cache: uuid.UUID | None = None


class EmbeddingStage(StrEnum):
    ORIGINAL = "original"
    TRANSLATED = "translated"
    ANNOTATION = "annotation"


@dataclass(frozen=True, slots=True)
class EmbedStageResult:
    stage: EmbeddingStage
    status: str  # skipped_disabled | skipped_empty | skipped_current | embedded | failed
    chunk_count: int = 0
    error: str | None = None


def content_fingerprint(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _fp_column(stage: EmbeddingStage) -> str:
    return {
        EmbeddingStage.ORIGINAL: "embedding_original_fp",
        EmbeddingStage.TRANSLATED: "embedding_translated_fp",
        EmbeddingStage.ANNOTATION: "embedding_annotation_fp",
    }[stage]


def _stored_fp(doc: Document, stage: EmbeddingStage) -> str | None:
    return getattr(doc, _fp_column(stage))


def _set_stored_fp(doc: Document, stage: EmbeddingStage, fp: str) -> None:
    setattr(doc, _fp_column(stage), fp)


def is_embedding_fresh(doc: Document, stage: EmbeddingStage) -> bool:
    """True, если fp совпадает с текущим текстом стадии (эмбеддинг не устарел)."""
    text, _lang = _resolve_stage_text_and_language(doc, stage)
    if not text:
        return False
    stored = _stored_fp(doc, stage)
    if not stored:
        return False
    return stored == content_fingerprint(text)


def _sql_normalized_content(column):  # noqa: ANN001
    return func.btrim(func.regexp_replace(column, r"\s+", " ", "g"))


def _sql_content_fingerprint(column):  # noqa: ANN001
    normalized = _sql_normalized_content(column)
    return func.encode(func.digest(func.convert_to(normalized, "UTF8"), "sha256"), "hex")


def _sql_annotation_text():
    translated = func.nullif(func.btrim(Document.translated_summary), "")
    original = func.nullif(func.btrim(Document.original_summary), "")
    return case(
        (
            translated.is_not(None)
            & original.is_not(None)
            & (translated != original),
            func.concat(translated, "\n\n---\n\n", original),
        ),
        else_=func.coalesce(translated, original),
    )


async def collect_embedding_counters(session: AsyncSession) -> dict[str, int]:
    """Документы с неустаревшим эмбеддингом: fp в БД совпадает с fp текущего текста."""
    orig_body = func.nullif(func.btrim(Document.original_content), "")
    orig_fp = _sql_content_fingerprint(Document.original_content)
    embedded_originals = int(
        await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                orig_body.is_not(None),
                Document.embedding_original_fp.is_not(None),
                Document.embedding_original_fp == orig_fp,
            ),
        )
        or 0,
    )

    trans_body = func.nullif(func.btrim(Document.translated_content), "")
    trans_fp = _sql_content_fingerprint(Document.translated_content)
    embedded_translations = int(
        await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                trans_body.is_not(None),
                Document.embedding_translated_fp.is_not(None),
                Document.embedding_translated_fp == trans_fp,
            ),
        )
        or 0,
    )

    ann_text = _sql_annotation_text()
    ann_body = func.nullif(ann_text, "")
    ann_fp = _sql_content_fingerprint(ann_text)
    embedded_annotations = int(
        await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                ann_body.is_not(None),
                Document.embedding_annotation_fp.is_not(None),
                Document.embedding_annotation_fp == ann_fp,
            ),
        )
        or 0,
    )

    return {
        "embedded_originals": embedded_originals,
        "embedded_translations": embedded_translations,
        "embedded_annotations": embedded_annotations,
    }


def _annotation_embed_text(doc: Document) -> str:
    translated = (doc.translated_summary or "").strip()
    original = (doc.original_summary or "").strip()
    if translated and original and translated != original:
        return f"{translated}\n\n---\n\n{original}"
    return translated or original


def _resolve_stage_text_and_language(
    doc: Document,
    stage: EmbeddingStage,
) -> tuple[str, uuid.UUID | None]:
    if stage == EmbeddingStage.ORIGINAL:
        return (doc.original_content or "").strip(), doc.original_language_id
    if stage == EmbeddingStage.TRANSLATED:
        return (doc.translated_content or "").strip(), doc.translated_language_id
    return _annotation_embed_text(doc), doc.translated_language_id or doc.original_language_id


def split_text_into_chunks(text: str, *, max_chars: int) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]
    out: list[str] = []
    start = 0
    while start < len(stripped):
        out.append(stripped[start : start + max_chars])
        start += max_chars
    return out


async def _embedding_model_id(session: AsyncSession) -> uuid.UUID:
    global _model_id_cache
    if _model_id_cache is not None:
        return _model_id_cache
    name = settings.embedding_catalog_model_name
    row = await session.scalar(select(EmbeddingModel.id).where(EmbeddingModel.name == name))
    if row is None:
        raise NotFoundError(f"Модель эмбеддингов {name!r} не найдена в embedding_models (запустите seed)")
    _model_id_cache = row
    return row


async def _delete_stage_chunks(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    language_id: uuid.UUID,
    chunk_type: str,
) -> None:
    await session.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.language_id == language_id,
            DocumentChunk.chunk_type == chunk_type,
        ),
    )


async def embed_document_if_stale(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    stage: EmbeddingStage,
) -> EmbedStageResult:
    if not settings.embedding_enabled:
        return EmbedStageResult(stage=stage, status="skipped_disabled")

    doc = await session.get(Document, document_id)
    if doc is None:
        raise NotFoundError("Документ не найден")

    text, language_id = _resolve_stage_text_and_language(doc, stage)
    if not text:
        return EmbedStageResult(stage=stage, status="skipped_empty")

    if language_id is None:
        if stage == EmbeddingStage.ANNOTATION:
            language_id = await language_id_by_code(session, "ru")
        else:
            return EmbedStageResult(stage=stage, status="skipped_empty")

    fp = content_fingerprint(text)
    if _stored_fp(doc, stage) == fp:
        return EmbedStageResult(stage=stage, status="skipped_current")

    chunk_type = stage.value
    try:
        model_id = await _embedding_model_id(session)
        await _delete_stage_chunks(
            session,
            document_id=document_id,
            language_id=language_id,
            chunk_type=chunk_type,
        )
        pieces = split_text_into_chunks(text, max_chars=settings.embedding_chunk_chars)
        if not pieces:
            return EmbedStageResult(stage=stage, status="skipped_empty")

        vectors = await create_embeddings(pieces)
        if len(vectors) != len(pieces):
            raise ExternalServiceError("TEI вернул число векторов, не совпадающее с числом чанков")

        for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
            chunk = DocumentChunk(
                document_id=document_id,
                language_id=language_id,
                chunk_type=chunk_type,
                chunk_index=index,
                content=piece,
            )
            session.add(chunk)
            await session.flush()
            stmt = insert(DocumentEmbedding).values(
                chunk_id=chunk.id,
                embedding_model_id=model_id,
                embedding=vector,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["chunk_id", "embedding_model_id"],
                set_={"embedding": stmt.excluded.embedding},
            )
            await session.execute(stmt)

        _set_stored_fp(doc, stage, fp)
        return EmbedStageResult(stage=stage, status="embedded", chunk_count=len(pieces))
    except Exception as exc:
        if settings.embedding_fail_open:
            _log.exception(
                "embedding failed document_id=%s stage=%s",
                document_id,
                stage.value,
            )
            return EmbedStageResult(stage=stage, status="failed", error=str(exc)[:2000])
        raise


async def embed_document_stages_if_stale(
    session: AsyncSession,
    *,
    document_id: uuid.UUID,
    stages: tuple[EmbeddingStage, ...],
) -> list[EmbedStageResult]:
    results: list[EmbedStageResult] = []
    for stage in stages:
        results.append(
            await embed_document_if_stale(session, document_id=document_id, stage=stage),
        )
    return results


async def embed_document_stages_best_effort(
    document_id: uuid.UUID,
    *stages: EmbeddingStage,
) -> None:
    """Отдельная сессия после commit транзакции создания/сохранения в API."""
    if not settings.embedding_enabled or not stages:
        return
    try:
        async with AsyncSessionLocal() as session:
            await embed_document_stages_if_stale(session, document_id=document_id, stages=stages)
            await session.commit()
    except Exception:
        _log.exception(
            "embedding best-effort failed document_id=%s stages=%s",
            document_id,
            [s.value for s in stages],
        )
