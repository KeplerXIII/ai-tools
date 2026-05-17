"""Типы RAG: чанки, фильтры, опции pipeline (расширяемые под hybrid / rerank)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class RetrievalStrategy(StrEnum):
    VECTOR = "vector"
    HYBRID = "hybrid"  # вектор + PostgreSQL FTS → RRF
    HYBRID_BM25 = "hybrid_bm25"  # вектор + Okapi BM25 → RRF
    HYBRID_ALL = "hybrid_all"  # вектор + FTS + BM25 → RRF (3 списка)


class RerankerKind(StrEnum):
    NONE = "none"
    CROSS_ENCODER = "cross_encoder"


@dataclass(frozen=True, slots=True)
class RetrievalFilters:
    fund_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    tag_ids: tuple[uuid.UUID, ...] = ()
    category_ids: tuple[uuid.UUID, ...] = ()
    entity_ids: tuple[uuid.UUID, ...] = ()
    published_from: datetime | None = None
    published_to: datetime | None = None


@dataclass(frozen=True, slots=True)
class RetrievalOptions:
    """Опции одного прохода retrieval (передаются в pipeline и backends)."""

    query: str
    fetch_k: int
    top_k: int
    sources_k: int  # сколько фрагментов отдать в API/UI (после rerank)
    chunk_types: tuple[str, ...]
    filters: RetrievalFilters = field(default_factory=RetrievalFilters)
    strategy: RetrievalStrategy = RetrievalStrategy.VECTOR
    reranker: RerankerKind = RerankerKind.NONE
    expand_query: bool = False
    max_chunks_per_document: int = 3
    max_context_tokens: int = 6000
    min_similarity: float | None = None
    rrf_k: int = 60


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    chunk_type: str
    chunk_index: int
    content: str
    title: str
    source_url: str | None
    distance: float
    score: float
    rank: int = 0  # после rerank / merge
    backend: str = "vector"
    # Score от vector / lexical / bm25 до RRF и rerank (только для UI/отладки).
    retrieval_scores: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RagAnswer:
    answer: str
    sources: tuple[RetrievedChunk, ...]
    context_sources: tuple[RetrievedChunk, ...]
    retrieval_ms: int
    generation_ms: int
