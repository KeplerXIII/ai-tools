from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RagFiltersSchema(BaseModel):
    fund_id: uuid.UUID | None = None
    environment_id: uuid.UUID | None = None
    source_id: uuid.UUID | None = None
    tag_ids: list[uuid.UUID] = Field(default_factory=list)
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    entity_ids: list[uuid.UUID] = Field(default_factory=list)
    published_from: datetime | None = None
    published_to: datetime | None = None


class RagAskRequest(BaseModel):
    query: str
    top_k: int | None = Field(default=None, ge=1, le=100)
    fetch_k: int | None = Field(default=None, ge=1, le=200)
    sources_k: int | None = Field(
        default=None,
        ge=1,
        le=200,
        description="Сколько фрагментов вернуть в sources (после rerank); по умолчанию = fetch_k.",
    )
    chunk_types: list[str] | None = None
    filters: RagFiltersSchema = Field(default_factory=RagFiltersSchema)
    retrieval_strategy: Literal["vector", "hybrid", "hybrid_bm25", "hybrid_all"] | None = None
    reranker: Literal["none", "cross_encoder"] | None = None
    expand_query: bool | None = None
    min_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Мин. score после rerank (или similarity без rerank). Пусто — из RAG_MIN_SIMILARITY или без отсечения.",
    )


class RagSourceSchema(BaseModel):
    document_id: uuid.UUID
    chunk_id: uuid.UUID
    title: str
    url: str | None = None
    excerpt: str
    chunk_type: str
    chunk_index: int
    score: float
    rank: int
    score_from: Literal["reranker", "retrieval"] = Field(
        default="retrieval",
        description="Источник поля score: cross-encoder reranker или retrieval (без rerank / хвост).",
    )
    retrieval_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Score до rerank: vector, lexical (FTS), bm25 — для сравнения в UI.",
    )
    citation_id: int | None = Field(
        default=None,
        description="Номер [N] в промпте LLM, если фрагмент вошёл в контекст ответа.",
    )


class RagAskResponse(BaseModel):
    answer: str | None = None
    sources: list[RagSourceSchema]
    context_sources: list[RagSourceSchema] = Field(
        default_factory=list,
        description="Фрагменты в промпте LLM ([1]…[top_k]), порядок = цитирование в ответе.",
    )
    retrieval_ms: int
    generation_ms: int | None = None
    retrieval_strategy: str | None = None
    reranker: str | None = None


class RagMetricsResponse(BaseModel):
    total_queries: int
    queries_last_24h: int
    avg_retrieval_ms: float | None
    avg_generation_ms: float | None
    empty_context_rate: float | None
