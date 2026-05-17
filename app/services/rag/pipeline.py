"""Оркестрация retrieval: expand → embed → backend(s) → RRF → rerank → postprocess."""

from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.domain.errors import ValidationError
from app.infrastructure.llm.clients.embedding_client import create_embeddings
from app.services.rag.backends.bm25 import Bm25RetrievalBackend
from app.services.rag.backends.lexical import LexicalRetrievalBackend
from app.services.rag.backends.vector import VectorRetrievalBackend
from app.services.rag.merge import reciprocal_rank_fusion
from app.services.rag.retrieval_scores import (
    attach_backend_scores,
    merge_backend_score_map,
    merge_retrieval_score_maps,
)
from app.services.rag.postprocess import (
    apply_max_chunks_per_document,
    filter_by_min_similarity,
    finalize_chunk_ranks,
    trim_chunks_by_token_budget,
)
from app.services.rag.query_expansion import expand_search_queries
from app.services.rag.rerankers import get_reranker, reranker_kind_from_settings
from app.services.rag.types import (
    RerankerKind,
    RetrievalOptions,
    RetrievalStrategy,
    RetrievedChunk,
)


def default_chunk_types() -> tuple[str, ...]:
    raw = (settings.rag_default_chunk_types or "").strip()
    if not raw:
        return ("translated", "original", "annotation")
    return tuple(t.strip() for t in raw.split(",") if t.strip())


def retrieval_strategy_from_settings() -> RetrievalStrategy:
    raw = (settings.rag_retrieval_strategy or "vector").strip().lower()
    try:
        return RetrievalStrategy(raw)
    except ValueError as exc:
        raise ValidationError(f"Неизвестный RAG_RETRIEVAL_STRATEGY: {raw!r}") from exc


def options_from_settings(
    *,
    query: str,
    fetch_k: int | None = None,
    top_k: int | None = None,
    chunk_types: tuple[str, ...] | None = None,
    strategy: RetrievalStrategy | None = None,
    reranker: RerankerKind | None = None,
    expand_query: bool | None = None,
    **overrides,
) -> RetrievalOptions:
    from app.services.rag.types import RetrievalFilters

    filters = overrides.pop("filters", None) or RetrievalFilters()
    resolved_fetch_k = fetch_k if fetch_k is not None else settings.rag_fetch_k
    resolved_sources_k = overrides.pop("sources_k", None)
    return RetrievalOptions(
        query=query,
        fetch_k=resolved_fetch_k,
        top_k=top_k if top_k is not None else settings.rag_top_k,
        sources_k=resolved_sources_k if resolved_sources_k is not None else resolved_fetch_k,
        chunk_types=chunk_types or default_chunk_types(),
        filters=filters,
        strategy=strategy or retrieval_strategy_from_settings(),
        reranker=reranker or reranker_kind_from_settings(),
        expand_query=(
            expand_query
            if expand_query is not None
            else settings.rag_query_expansion
        ),
        max_chunks_per_document=overrides.get(
            "max_chunks_per_document",
            settings.rag_max_chunks_per_document,
        ),
        max_context_tokens=overrides.get("max_context_tokens", settings.rag_max_context_tokens),
        min_similarity=overrides.get("min_similarity", settings.rag_min_similarity),
        rrf_k=overrides.get("rrf_k", settings.rag_rrf_k),
    )


class RetrievalPipeline:
    def __init__(
        self,
        *,
        vector_backend: VectorRetrievalBackend | None = None,
        lexical_backend: LexicalRetrievalBackend | None = None,
    ) -> None:
        self._vector = vector_backend or VectorRetrievalBackend()
        self._lexical_fts = lexical_backend or LexicalRetrievalBackend()
        self._lexical_bm25 = Bm25RetrievalBackend()

    async def retrieve(
        self,
        session: AsyncSession,
        options: RetrievalOptions,
    ) -> tuple[tuple[RetrievedChunk, ...], tuple[RetrievedChunk, ...], int, list[str]]:
        started = time.perf_counter()
        if not settings.rag_enabled:
            raise ValidationError("RAG отключён (RAG_ENABLED=false)")

        query = options.query.strip()
        if not query:
            raise ValidationError("Запрос пустой")

        search_queries = (
            await expand_search_queries(query)
            if options.expand_query
            else [query]
        )

        candidate_lists: list[list[RetrievedChunk]] = []
        for sub_query in search_queries:
            vectors = await create_embeddings([sub_query])
            if not vectors:
                continue
            hits = await self._fetch_for_query_vector(
                session,
                options,
                query=sub_query,
                query_vector=vectors[0],
            )
            if hits:
                candidate_lists.append(hits)

        if len(candidate_lists) > 1:
            candidates = reciprocal_rank_fusion(
                candidate_lists,
                k=options.rrf_k,
                key=lambda c: c.chunk_id,
            )[: options.fetch_k]
            score_maps = [
                {c.chunk_id: dict(c.retrieval_scores) for c in lst}
                for lst in candidate_lists
            ]
            candidates = attach_backend_scores(
                candidates,
                merge_retrieval_score_maps(*score_maps),
            )
        elif candidate_lists:
            candidates = candidate_lists[0][: options.fetch_k]
        else:
            candidates = []

        reranker = get_reranker(options.reranker)
        ranked = await reranker.rerank(
            query,
            candidates,
            top_k=options.fetch_k,
        )

        ranked = filter_by_min_similarity(ranked, min_similarity=options.min_similarity)
        ranked = apply_max_chunks_per_document(
            ranked,
            max_per_document=options.max_chunks_per_document,
        )
        sources = finalize_chunk_ranks(ranked[: options.sources_k])

        context = trim_chunks_by_token_budget(
            ranked,
            max_tokens=options.max_context_tokens,
        )
        context = finalize_chunk_ranks(context[: options.top_k])

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return sources, context, elapsed_ms, search_queries

    async def _fetch_for_query_vector(
        self,
        session: AsyncSession,
        options: RetrievalOptions,
        *,
        query: str,
        query_vector: list[float],
    ) -> list[RetrievedChunk]:
        ranked_lists = await self._hybrid_ranked_lists(
            session,
            options,
            query=query,
            query_vector=query_vector,
        )
        if ranked_lists is not None:
            if len(ranked_lists) == 1:
                merged = ranked_lists[0][: options.fetch_k]
            else:
                merged = reciprocal_rank_fusion(
                    ranked_lists,
                    k=options.rrf_k,
                    key=lambda c: c.chunk_id,
                )[: options.fetch_k]
            scores_by_chunk = await self._diagnostic_retrieval_scores(
                session,
                options,
                query=query,
                query_vector=query_vector,
                chunk_ids=[c.chunk_id for c in merged],
            )
            return attach_backend_scores(merged, scores_by_chunk)

        vector_hits = await self._vector.search(
            session,
            query=query,
            query_vector=query_vector,
            fetch_k=options.fetch_k,
            chunk_types=options.chunk_types,
            filters=options.filters,
        )
        scores_by_chunk = await self._diagnostic_retrieval_scores(
            session,
            options,
            query=query,
            query_vector=query_vector,
            chunk_ids=[c.chunk_id for c in vector_hits],
        )
        return attach_backend_scores(vector_hits, scores_by_chunk)

    async def _hybrid_ranked_lists(
        self,
        session: AsyncSession,
        options: RetrievalOptions,
        *,
        query: str,
        query_vector: list[float],
    ) -> list[list[RetrievedChunk]] | None:
        """None — не гибрид; иначе 2–3 списка кандидатов для RRF."""
        strategy = options.strategy
        if strategy == RetrievalStrategy.VECTOR:
            return None

        search_kw = dict(
            query=query,
            query_vector=query_vector,
            fetch_k=options.fetch_k,
            chunk_types=options.chunk_types,
            filters=options.filters,
        )
        lists: list[list[RetrievedChunk]] = [
            await self._vector.search(session, **search_kw),
        ]

        if strategy in (RetrievalStrategy.HYBRID, RetrievalStrategy.HYBRID_ALL):
            lists.append(await self._lexical_fts.search(session, **search_kw))

        if strategy in (RetrievalStrategy.HYBRID_BM25, RetrievalStrategy.HYBRID_ALL):
            lists.append(await self._lexical_bm25.search(session, **search_kw))

        return lists

    async def _diagnostic_retrieval_scores(
        self,
        session: AsyncSession,
        options: RetrievalOptions,
        *,
        query: str,
        query_vector: list[float],
        chunk_ids: list,
    ) -> dict:
        """Score vector/FTS/BM25 для финальных chunk_id (только UI, не влияет на RRF/rerank)."""
        if not chunk_ids:
            return {}

        ids = list(chunk_ids)
        strategy = options.strategy
        kw = dict(
            chunk_types=options.chunk_types,
            filters=options.filters,
        )
        out: dict = {cid: {} for cid in ids}

        merge_backend_score_map(
            out,
            "vector",
            await self._vector.score_chunks(
                session,
                query_vector=query_vector,
                chunk_ids=ids,
                **kw,
            ),
        )

        if strategy in (RetrievalStrategy.HYBRID, RetrievalStrategy.HYBRID_ALL):
            merge_backend_score_map(
                out,
                "lexical",
                await self._lexical_fts.score_chunks(
                    session,
                    query=query,
                    chunk_ids=ids,
                    **kw,
                ),
            )

        if strategy in (RetrievalStrategy.HYBRID_BM25, RetrievalStrategy.HYBRID_ALL):
            merge_backend_score_map(
                out,
                "bm25",
                await self._lexical_bm25.score_chunks(
                    session,
                    query=query,
                    chunk_ids=ids,
                    **kw,
                ),
            )

        return out
