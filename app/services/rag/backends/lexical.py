"""Лексический поиск (PostgreSQL FTS, russian) для hybrid RAG."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, type_coerce
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.db.models import Document, DocumentChunk
from app.services.rag.backends.document_title import document_display_title_column
from app.services.rag.backends.filters import apply_document_metadata_filters
from app.services.rag.types import RetrievalFilters, RetrievedChunk

# Нормализация rank в [0, 1] для сопоставления с vector score в RRF
_RANK_SCALE = 10.0


class LexicalRetrievalBackend:
    name = "lexical"

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str,
        query_vector: list[float],
        fetch_k: int,
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> list[RetrievedChunk]:
        del query_vector
        q = query.strip()
        if not q or fetch_k < 1:
            return []

        config = settings.rag_fts_config
        ts_query = func.plainto_tsquery(config, q)
        doc_vector = func.to_tsvector(config, func.coalesce(DocumentChunk.content, ""))
        rank_expr = func.ts_rank_cd(doc_vector, ts_query)

        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.document_id,
                DocumentChunk.chunk_type,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                document_display_title_column(),
                Document.source_url,
                rank_expr.label("rank"),
            )
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(type_coerce(doc_vector, TSVECTOR).op("@@")(ts_query))
        )

        if chunk_types:
            stmt = stmt.where(DocumentChunk.chunk_type.in_(chunk_types))

        stmt = apply_document_metadata_filters(stmt, filters)
        stmt = stmt.order_by(rank_expr.desc()).limit(fetch_k)

        rows = (await session.execute(stmt)).all()
        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                chunk_type=row.chunk_type,
                chunk_index=row.chunk_index,
                content=row.content,
                title=row.title,
                source_url=row.source_url,
                distance=1.0 - min(float(row.rank) / _RANK_SCALE, 1.0),
                score=min(float(row.rank) / _RANK_SCALE, 1.0),
                backend=self.name,
            )
            for row in rows
        ]

    async def score_chunks(
        self,
        session: AsyncSession,
        *,
        query: str,
        chunk_ids: list[uuid.UUID],
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> dict[uuid.UUID, float]:
        """ts_rank_cd для chunk_id (0 если нет лексического совпадения с запросом)."""
        q = query.strip()
        if not q or not chunk_ids:
            return {}

        config = settings.rag_fts_config
        ts_query = func.plainto_tsquery(config, q)
        doc_vector = func.to_tsvector(config, func.coalesce(DocumentChunk.content, ""))
        rank_expr = func.ts_rank_cd(doc_vector, ts_query)

        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                rank_expr.label("rank"),
            )
            .select_from(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.id.in_(chunk_ids))
        )
        if chunk_types:
            stmt = stmt.where(DocumentChunk.chunk_type.in_(chunk_types))
        stmt = apply_document_metadata_filters(stmt, filters)

        rows = (await session.execute(stmt)).all()
        scored = {
            row.chunk_id: min(float(row.rank) / _RANK_SCALE, 1.0)
            for row in rows
        }
        return {cid: scored.get(cid, 0.0) for cid in chunk_ids}
