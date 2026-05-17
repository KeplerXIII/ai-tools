"""Персистентный лог RAG-запросов (rag_queries)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import RagQuery
from app.services.rag.types import RetrievalFilters, RetrievalOptions, RetrievedChunk


def _filters_to_json(filters: RetrievalFilters) -> dict:
    return {
        "fund_id": str(filters.fund_id) if filters.fund_id else None,
        "environment_id": str(filters.environment_id) if filters.environment_id else None,
        "source_id": str(filters.source_id) if filters.source_id else None,
        "tag_ids": [str(x) for x in filters.tag_ids],
        "category_ids": [str(x) for x in filters.category_ids],
        "entity_ids": [str(x) for x in filters.entity_ids],
        "published_from": filters.published_from.isoformat() if filters.published_from else None,
        "published_to": filters.published_to.isoformat() if filters.published_to else None,
    }


async def log_rag_query(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    options: RetrievalOptions,
    expanded_queries: list[str] | None,
    chunks: tuple[RetrievedChunk, ...],
    retrieve_only: bool,
    retrieval_ms: int,
    generation_ms: int | None,
    error_message: str | None = None,
) -> uuid.UUID:
    row = RagQuery(
        user_id=user_id,
        query=options.query,
        expanded_queries=expanded_queries,
        retrieval_strategy=options.strategy.value,
        reranker=options.reranker.value,
        filters=_filters_to_json(options.filters),
        chunk_ids=[str(c.chunk_id) for c in chunks],
        retrieve_only=retrieve_only,
        retrieval_ms=retrieval_ms,
        generation_ms=generation_ms,
        error_message=error_message,
    )
    session.add(row)
    await session.flush()
    return row.id
