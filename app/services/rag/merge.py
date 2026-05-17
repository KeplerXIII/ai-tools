"""Слияние ранжированных списков (RRF) для hybrid search — фаза 3."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[T]],
    *,
    k: int = 60,
    key: Callable[[T], Hashable],
) -> list[T]:
    """Reciprocal Rank Fusion: объединяет vector + lexical (или multi-query) без калибровки score."""
    scores: dict[Hashable, float] = {}
    items: dict[Hashable, T] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked, start=1):
            item_key = key(item)
            scores[item_key] = scores.get(item_key, 0.0) + 1.0 / (k + rank)
            items[item_key] = item
    ordered = sorted(scores.keys(), key=lambda ik: scores[ik], reverse=True)
    return [items[ik] for ik in ordered]
