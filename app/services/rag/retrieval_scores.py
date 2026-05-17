"""Сбор score по бэкендам для отладки/UI (не влияет на RRF и rerank)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace

from app.services.rag.types import RetrievedChunk


def index_backend_scores(
    ranked_lists: Sequence[Sequence[RetrievedChunk]],
) -> dict[uuid.UUID, dict[str, float]]:
    """chunk_id → {backend_name: score} из каждого списка hybrid retrieval."""
    out: dict[uuid.UUID, dict[str, float]] = {}
    for ranked in ranked_lists:
        for item in ranked:
            backend = (item.backend or "vector").split("+", 1)[0]
            out.setdefault(item.chunk_id, {})[backend] = float(item.score)
    return out


def merge_retrieval_score_maps(
    *maps: dict[uuid.UUID, dict[str, float]],
) -> dict[uuid.UUID, dict[str, float]]:
    """Объединение при multi-query: для каждого backend берём max score."""
    merged: dict[uuid.UUID, dict[str, float]] = {}
    for score_map in maps:
        for chunk_id, backends in score_map.items():
            bucket = merged.setdefault(chunk_id, {})
            for backend, score in backends.items():
                bucket[backend] = max(bucket.get(backend, 0.0), float(score))
    return merged


def merge_backend_score_map(
    target: dict[uuid.UUID, dict[str, float]],
    backend: str,
    scores: dict[uuid.UUID, float],
) -> None:
    for chunk_id, score in scores.items():
        target.setdefault(chunk_id, {})[backend] = float(score)


def attach_backend_scores(
    chunks: Sequence[RetrievedChunk],
    scores_by_chunk: dict[uuid.UUID, dict[str, float]],
) -> list[RetrievedChunk]:
    if not scores_by_chunk:
        return list(chunks)
    out: list[RetrievedChunk] = []
    for c in chunks:
        scores = scores_by_chunk.get(c.chunk_id)
        if scores is None:
            out.append(c)
        else:
            out.append(replace(c, retrieval_scores=dict(scores)))
    return out
