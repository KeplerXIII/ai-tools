"""Постобработка кандидатов: dedup по документу, лимит токенов контекста."""

from __future__ import annotations

from app.services.documents.embedding_chunking import count_embedding_tokens
from app.services.rag.types import RetrievedChunk


def apply_max_chunks_per_document(
    chunks: list[RetrievedChunk],
    *,
    max_per_document: int,
) -> list[RetrievedChunk]:
    if max_per_document < 1:
        return chunks
    counts: dict = {}
    out: list[RetrievedChunk] = []
    for chunk in chunks:
        n = counts.get(chunk.document_id, 0)
        if n >= max_per_document:
            continue
        counts[chunk.document_id] = n + 1
        out.append(chunk)
    return out


def trim_chunks_by_token_budget(
    chunks: list[RetrievedChunk],
    *,
    max_tokens: int,
) -> list[RetrievedChunk]:
    if max_tokens <= 0:
        return []
    total = 0
    out: list[RetrievedChunk] = []
    for chunk in chunks:
        piece_tokens = count_embedding_tokens(chunk.content)
        if total + piece_tokens > max_tokens and out:
            break
        if piece_tokens > max_tokens and not out:
            out.append(chunk)
            break
        total += piece_tokens
        out.append(chunk)
    return out


def filter_by_min_score(
    chunks: list[RetrievedChunk],
    *,
    min_score: float | None,
) -> list[RetrievedChunk]:
    """Отсечение слабых кандидатов по score (после rerank — relevance TEI, иначе similarity/норм. backend)."""
    if min_score is None or min_score <= 0:
        return chunks
    return [c for c in chunks if c.score >= min_score]


def filter_by_min_similarity(
    chunks: list[RetrievedChunk],
    *,
    min_similarity: float | None,
) -> list[RetrievedChunk]:
    return filter_by_min_score(chunks, min_score=min_similarity)


def finalize_chunk_ranks(chunks: list[RetrievedChunk]) -> tuple[RetrievedChunk, ...]:
    return tuple(
        RetrievedChunk(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            chunk_type=c.chunk_type,
            chunk_index=c.chunk_index,
            content=c.content,
            title=c.title,
            source_url=c.source_url,
            distance=c.distance,
            score=c.score,
            rank=index,
            backend=c.backend,
            retrieval_scores=dict(c.retrieval_scores),
        )
        for index, c in enumerate(chunks, start=1)
    )
