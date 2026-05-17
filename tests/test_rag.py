from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.rag.merge import reciprocal_rank_fusion
from app.services.rag.pipeline import RetrievalPipeline, options_from_settings
from app.services.rag.retrieval_scores import attach_backend_scores, index_backend_scores
from app.services.rag.postprocess import (
    apply_max_chunks_per_document,
    filter_by_min_similarity,
    trim_chunks_by_token_budget,
)
from app.services.rag.prompt_builder import build_rag_prompt
from app.services.rag.scoring import cosine_distance_to_similarity
from app.services.rag.types import RerankerKind, RetrievedChunk


def _chunk(
    *,
    doc_id: uuid.UUID | None = None,
    score: float = 0.9,
    content: str = "text",
    rank: int = 0,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=doc_id or uuid.uuid4(),
        chunk_type="translated",
        chunk_index=0,
        content=content,
        title="Title",
        source_url=None,
        distance=1.0 - score,
        score=score,
        rank=rank,
    )


def test_index_backend_scores_from_hybrid_lists() -> None:
    cid = uuid.uuid4()
    doc = uuid.uuid4()
    v = RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        chunk_type="translated",
        chunk_index=0,
        content="a",
        title="T",
        source_url=None,
        distance=0.2,
        score=0.8,
        backend="vector",
    )
    f = RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        chunk_type="translated",
        chunk_index=0,
        content="a",
        title="T",
        source_url=None,
        distance=0.5,
        score=0.15,
        backend="lexical",
    )
    b = RetrievedChunk(
        chunk_id=cid,
        document_id=doc,
        chunk_type="translated",
        chunk_index=0,
        content="a",
        title="T",
        source_url=None,
        distance=0.3,
        score=0.6,
        backend="bm25",
    )
    indexed = index_backend_scores([[v], [f], [b]])
    assert indexed[cid] == {"vector": 0.8, "lexical": 0.15, "bm25": 0.6}
    attached = attach_backend_scores([v], indexed)[0]
    assert attached.retrieval_scores == indexed[cid]


def test_cosine_distance_to_similarity() -> None:
    assert cosine_distance_to_similarity(0.0) == 1.0
    assert cosine_distance_to_similarity(1.0) == 0.0
    assert cosine_distance_to_similarity(2.0) == 0.0


def test_apply_max_chunks_per_document() -> None:
    doc = uuid.uuid4()
    chunks = [_chunk(doc_id=doc), _chunk(doc_id=doc), _chunk(doc_id=doc), _chunk()]
    out = apply_max_chunks_per_document(chunks, max_per_document=2)
    assert len(out) == 3


def test_filter_by_min_similarity() -> None:
    chunks = [_chunk(score=0.9), _chunk(score=0.3)]
    out = filter_by_min_similarity(chunks, min_similarity=0.5)
    assert len(out) == 1
    assert out[0].score == 0.9


def test_filter_by_min_score_zero_means_disabled() -> None:
    from app.services.rag.postprocess import filter_by_min_score

    chunks = [_chunk(score=0.9), _chunk(score=0.05)]
    assert len(filter_by_min_score(chunks, min_score=0)) == 2
    assert len(filter_by_min_score(chunks, min_score=None)) == 2
    assert len(filter_by_min_score(chunks, min_score=0.1)) == 1


def test_reciprocal_rank_fusion() -> None:
    chunk_a = _chunk(rank=1)
    chunk_b = _chunk(rank=2)
    chunk_c = _chunk(rank=3)
    list1 = [chunk_a, chunk_b]
    list2 = [chunk_b, chunk_c]
    merged = reciprocal_rank_fusion([list1, list2], key=lambda x: x.chunk_id)
    assert len(merged) == 3
    assert merged[0].chunk_id == chunk_b.chunk_id


def test_build_rag_prompt_includes_sources() -> None:
    chunks = (_chunk(content="факт один", rank=1),)
    prompt = build_rag_prompt(query="Что?", chunks=chunks)
    assert "Источник [1]" in prompt
    assert "факт один" in prompt
    assert "Что?" in prompt


def test_pipeline_retrieve_with_mocks() -> None:
    doc_id = uuid.uuid4()
    hit = _chunk(doc_id=doc_id, score=0.95)

    session = AsyncMock()
    session.execute = AsyncMock()

    vector_backend = AsyncMock()
    vector_backend.search = AsyncMock(return_value=[hit])
    vector_backend.score_chunks = AsyncMock(
        return_value={hit.chunk_id: hit.score},
    )

    with (
        patch("app.services.rag.pipeline.settings") as mock_settings,
        patch(
            "app.services.rag.pipeline.create_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 1024],
        ),
    ):
        mock_settings.rag_enabled = True
        mock_settings.rag_fetch_k = 10
        mock_settings.rag_top_k = 5
        mock_settings.rag_max_chunks_per_document = 3
        mock_settings.rag_max_context_tokens = 100_000
        mock_settings.rag_min_similarity = None
        mock_settings.rag_retrieval_strategy = "vector"
        mock_settings.rag_reranker = "none"
        mock_settings.rag_default_chunk_types = "translated"

        pipeline = RetrievalPipeline(vector_backend=vector_backend)
        opts = options_from_settings(query="тестовый запрос", reranker=RerankerKind.NONE)
        sources, _context, ms, _expanded = asyncio.run(pipeline.retrieve(session, opts))
        chunks = sources

    assert ms >= 0
    assert len(chunks) == 1
    assert chunks[0].rank == 1
    vector_backend.search.assert_awaited_once()


def test_hybrid_all_rrf_three_lists() -> None:
    from app.services.rag.merge import reciprocal_rank_fusion
    from app.services.rag.types import RetrievedChunk

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    v = RetrievedChunk(
        chunk_id=a,
        document_id=uuid.uuid4(),
        chunk_type="t",
        chunk_index=0,
        content="v",
        title="T",
        source_url=None,
        distance=0.1,
        score=0.9,
        backend="vector",
    )
    f = RetrievedChunk(
        chunk_id=b,
        document_id=uuid.uuid4(),
        chunk_type="t",
        chunk_index=0,
        content="f",
        title="T",
        source_url=None,
        distance=0.1,
        score=0.8,
        backend="lexical",
    )
    m = RetrievedChunk(
        chunk_id=c,
        document_id=uuid.uuid4(),
        chunk_type="t",
        chunk_index=0,
        content="m",
        title="T",
        source_url=None,
        distance=0.1,
        score=0.85,
        backend="bm25",
    )
    merged = reciprocal_rank_fusion([[v], [f], [m]], key=lambda x: x.chunk_id, k=60)
    assert len(merged) == 3


def test_hybrid_strategy_merges_vector_and_lexical() -> None:
    from app.services.rag.types import RetrievalOptions, RetrievalStrategy

    session = AsyncMock()
    session.execute = AsyncMock()
    hit_v = _chunk(score=0.9)
    hit_l = RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        chunk_type="translated",
        chunk_index=1,
        content="lexical hit",
        title="Lex",
        source_url=None,
        distance=0.2,
        score=0.85,
        backend="lexical",
    )

    vector_backend = AsyncMock()
    vector_backend.search = AsyncMock(return_value=[hit_v])
    vector_backend.score_chunks = AsyncMock(
        side_effect=lambda _session, **kw: {cid: hit_v.score for cid in kw["chunk_ids"]},
    )
    lexical_backend = AsyncMock()
    lexical_backend.search = AsyncMock(return_value=[hit_l])
    lexical_backend.score_chunks = AsyncMock(
        side_effect=lambda _session, **kw: {cid: hit_l.score if cid == hit_l.chunk_id else 0.0 for cid in kw["chunk_ids"]},
    )

    opts = RetrievalOptions(
        query="q",
        fetch_k=5,
        top_k=3,
        sources_k=5,
        chunk_types=("translated",),
        strategy=RetrievalStrategy.HYBRID,
    )

    with (
        patch("app.services.rag.pipeline.settings") as mock_settings,
        patch(
            "app.services.rag.pipeline.create_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.0] * 1024],
        ),
    ):
        mock_settings.rag_enabled = True
        mock_settings.rag_max_chunks_per_document = 3
        mock_settings.rag_max_context_tokens = 100_000
        mock_settings.rag_min_similarity = None
        mock_settings.rag_top_k = 3
        mock_settings.rag_rrf_k = 60

        pipeline = RetrievalPipeline(
            vector_backend=vector_backend,
            lexical_backend=lexical_backend,
        )
        sources, _context, _ms, _exp = asyncio.run(pipeline.retrieve(session, opts))
        chunks = sources

    assert len(chunks) >= 1
    vector_backend.search.assert_awaited()
    lexical_backend.search.assert_awaited()


def test_cross_encoder_reranker_reorders() -> None:
    from app.services.rag.rerankers import CrossEncoderReranker

    c_first = _chunk(score=0.2)
    c_second = _chunk(score=0.9)

    with patch(
        "app.services.rag.rerankers.rerank_texts",
        new_callable=AsyncMock,
        return_value=[0.1, 0.95],
    ):
        out = asyncio.run(
            CrossEncoderReranker().rerank("q", [c_first, c_second], top_k=2),
        )

    assert out[0].chunk_id == c_second.chunk_id
    assert out[0].score == 0.95


def test_cross_encoder_reranks_rrf_order_not_retrieval_score() -> None:
    from app.services.rag.rerankers import CrossEncoderReranker

    c_rrf_first = _chunk(score=0.1, content="rrf-first")
    c_rrf_second = _chunk(score=0.99, content="rrf-second")
    mock_rerank = AsyncMock(return_value=[0.5, 0.5])

    with patch("app.services.rag.rerankers.rerank_texts", mock_rerank):
        asyncio.run(
            CrossEncoderReranker().rerank("q", [c_rrf_first, c_rrf_second], top_k=2),
        )

    assert mock_rerank.await_args.args[1] == ["rrf-first", "rrf-second"]


def test_cross_encoder_caps_texts_at_tei_batch_size() -> None:
    from app.services.rag.rerankers import CrossEncoderReranker

    candidates = [_chunk(score=1.0 - i * 0.01) for i in range(40)]
    mock_rerank = AsyncMock(return_value=[0.5] * 32)

    with (
        patch("app.services.rag.rerankers.settings") as mock_settings,
        patch("app.services.rag.rerankers.rerank_texts", mock_rerank),
    ):
        mock_settings.rag_rerank_max_batch_size = 32
        asyncio.run(CrossEncoderReranker().rerank("q", candidates, top_k=40))

    assert len(mock_rerank.await_args.args[1]) == 32


def test_cross_encoder_tail_keeps_retrieval_backend() -> None:
    from app.services.rag.rerankers import CrossEncoderReranker

    candidates = [_chunk(score=0.9 - i * 0.01, content=f"c{i}") for i in range(34)]
    mock_rerank = AsyncMock(return_value=[0.1] * 32)

    with (
        patch("app.services.rag.rerankers.settings") as mock_settings,
        patch("app.services.rag.rerankers.rerank_texts", mock_rerank),
    ):
        mock_settings.rag_rerank_max_batch_size = 32
        out = asyncio.run(CrossEncoderReranker().rerank("q", candidates, top_k=34))

    assert len(out) == 34
    assert out[0].backend == "rerank"
    assert out[-1].backend != "rerank"
    assert out[-1].score == candidates[-1].score
