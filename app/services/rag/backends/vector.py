"""Векторный поиск по document_embeddings (cosine, HNSW)."""

from __future__ import annotations

import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infrastructure.db.models import (
    Document,
    DocumentChunk,
    DocumentEmbedding,
)
from app.services.documents.document_embedding import resolve_embedding_model_id
from app.services.rag.backends.document_title import document_display_title_column
from app.services.rag.backends.filters import apply_document_metadata_filters
from app.services.rag.scoring import cosine_distance_to_similarity
from app.services.rag.types import RetrievalFilters, RetrievedChunk


class VectorRetrievalBackend:
    name = "vector"

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
        del query
        if not query_vector:
            return []
        if fetch_k < 1:
            return []

        # SET не поддерживает bind-параметры в PostgreSQL — только литерал int.
        ef_search = max(1, min(int(settings.rag_hnsw_ef_search), 10_000))
        await session.execute(text(f"SET LOCAL hnsw.ef_search = {ef_search}"))

        model_id = await resolve_embedding_model_id(session)
        distance_expr = DocumentEmbedding.embedding.cosine_distance(query_vector)

        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                DocumentChunk.document_id,
                DocumentChunk.chunk_type,
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                document_display_title_column(),
                Document.source_url,
                distance_expr.label("distance"),
            )
            .select_from(DocumentEmbedding)
            .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentEmbedding.embedding_model_id == model_id)
        )

        if chunk_types:
            stmt = stmt.where(DocumentChunk.chunk_type.in_(chunk_types))

        stmt = apply_document_metadata_filters(stmt, filters)
        stmt = stmt.order_by(distance_expr).limit(fetch_k)

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
                distance=float(row.distance),
                score=cosine_distance_to_similarity(float(row.distance)),
                backend=self.name,
            )
            for row in rows
        ]

    async def score_chunks(
        self,
        session: AsyncSession,
        *,
        query_vector: list[float],
        chunk_ids: list[uuid.UUID],
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> dict[uuid.UUID, float]:
        """Cosine similarity для конкретных chunk_id (для UI, не меняет ранжирование)."""
        if not query_vector or not chunk_ids:
            return {}

        model_id = await resolve_embedding_model_id(session)
        distance_expr = DocumentEmbedding.embedding.cosine_distance(query_vector)

        stmt = (
            select(
                DocumentChunk.id.label("chunk_id"),
                distance_expr.label("distance"),
            )
            .select_from(DocumentEmbedding)
            .join(DocumentChunk, DocumentChunk.id == DocumentEmbedding.chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentEmbedding.embedding_model_id == model_id,
                DocumentChunk.id.in_(chunk_ids),
            )
        )
        if chunk_types:
            stmt = stmt.where(DocumentChunk.chunk_type.in_(chunk_types))
        stmt = apply_document_metadata_filters(stmt, filters)

        rows = (await session.execute(stmt)).all()
        return {
            row.chunk_id: cosine_distance_to_similarity(float(row.distance))
            for row in rows
        }
