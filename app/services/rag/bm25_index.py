"""Синхронизация инвертированного индекса BM25 при изменении чанков."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DocumentChunkTerm
from app.services.rag.bm25_tokenize import term_frequencies


async def sync_bm25_terms_for_chunk(
    session: AsyncSession,
    *,
    chunk_id: uuid.UUID,
    content: str,
) -> int:
    """Пересобирает термы чанка. Возвращает число уникальных термов."""
    tf_map = term_frequencies(content)
    await session.execute(
        delete(DocumentChunkTerm).where(DocumentChunkTerm.chunk_id == chunk_id),
    )
    for term, tf in tf_map.items():
        session.add(DocumentChunkTerm(chunk_id=chunk_id, term=term, tf=tf))
    return len(tf_map)


async def fetch_bm25_corpus_stats(session: AsyncSession) -> tuple[int, float]:
    """Число проиндексированных чанков и средняя длина (сумма tf)."""
    corpus_size = await session.scalar(
        select(func.count(func.distinct(DocumentChunkTerm.chunk_id))),
    )
    corpus_size = int(corpus_size or 0)
    if corpus_size == 0:
        return 0, 0.0

    lengths = (
        select(
            DocumentChunkTerm.chunk_id.label("chunk_id"),
            func.sum(DocumentChunkTerm.tf).label("dl"),
        )
        .group_by(DocumentChunkTerm.chunk_id)
        .subquery()
    )
    avg_dl = await session.scalar(select(func.avg(lengths.c.dl)))
    return corpus_size, float(avg_dl or 0.0)
