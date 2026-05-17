"""Reranker plug-in: no-op или cross-encoder (TEI /rerank + bi-encoder fallback)."""

from __future__ import annotations

import logging
from typing import Protocol

from app.core.config import settings
from app.domain.errors import ValidationError
from app.infrastructure.llm.clients.rerank_client import rerank_texts
from app.services.rag.types import RerankerKind, RetrievedChunk

_log = logging.getLogger(__name__)


class Reranker(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        ...


class NoOpReranker:
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        del query
        return candidates[:top_k]


class CrossEncoderReranker:
    async def rerank(
        self,
        query: str,
        candidates: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        if not candidates:
            return []
        tei_cap = max(1, settings.rag_rerank_max_batch_size)
        to_rerank = candidates[:tei_cap]
        tail = candidates[tei_cap:]
        if tail:
            _log.info(
                "Rerank: %s чанков вне TEI batch (лимит %s), score остаётся от retrieval",
                len(tail),
                tei_cap,
            )

        texts = [c.content for c in to_rerank]
        scores = await rerank_texts(query, texts)
        if len(scores) != len(to_rerank):
            return candidates[:top_k]

        ranked_pairs = sorted(
            zip(to_rerank, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )

        out: list[RetrievedChunk] = []
        for chunk, score in ranked_pairs:
            out.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    chunk_type=chunk.chunk_type,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    title=chunk.title,
                    source_url=chunk.source_url,
                    distance=max(0.0, 1.0 - score),
                    score=float(score),
                    rank=chunk.rank,
                    backend="rerank",
                    retrieval_scores=dict(chunk.retrieval_scores),
                ),
            )

        # Хвост: только retrieval-score, без +rerank (не путать с cross-encoder).
        if len(out) < top_k and tail:
            for chunk in tail[: top_k - len(out)]:
                out.append(
                    RetrievedChunk(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        chunk_type=chunk.chunk_type,
                        chunk_index=chunk.chunk_index,
                        content=chunk.content,
                        title=chunk.title,
                        source_url=chunk.source_url,
                        distance=chunk.distance,
                        score=chunk.score,
                        rank=chunk.rank,
                        backend=chunk.backend,
                        retrieval_scores=dict(chunk.retrieval_scores),
                    ),
                )

        return out[:top_k]


def get_reranker(kind: RerankerKind) -> Reranker:
    if kind == RerankerKind.NONE:
        return NoOpReranker()
    if kind == RerankerKind.CROSS_ENCODER:
        return CrossEncoderReranker()
    raise ValidationError(f"Неизвестный reranker: {kind!r}")


def reranker_kind_from_settings() -> RerankerKind:
    from app.core.config import settings

    raw = (settings.rag_reranker or "none").strip().lower()
    try:
        return RerankerKind(raw)
    except ValueError as exc:
        raise ValidationError(f"Неизвестный RAG_RERANKER: {raw!r}") from exc
