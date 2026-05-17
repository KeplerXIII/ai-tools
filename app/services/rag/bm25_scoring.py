"""Okapi BM25 scoring (rank_bm25-совместимая формула)."""

from __future__ import annotations

import math
import uuid


def bm25_idf(df: int, corpus_size: int) -> float:
    if corpus_size <= 0:
        return 0.0
    return math.log((corpus_size - df + 0.5) / (df + 0.5) + 1.0)


def bm25_score_document(
    query_terms: list[str],
    *,
    term_tf: dict[str, int],
    doc_length: int,
    term_df: dict[str, int],
    corpus_size: int,
    avg_doc_length: float,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    if not query_terms or corpus_size <= 0 or doc_length <= 0:
        return 0.0
    avg_dl = avg_doc_length if avg_doc_length > 0 else 1.0
    score = 0.0
    for term in query_terms:
        tf = term_tf.get(term, 0)
        if tf <= 0:
            continue
        df = term_df.get(term, 0)
        if df <= 0:
            continue
        idf = bm25_idf(df, corpus_size)
        denom = tf + k1 * (1.0 - b + b * (doc_length / avg_dl))
        score += idf * (tf * (k1 + 1.0)) / denom
    return score


def normalize_bm25_scores(scores: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
    if not scores:
        return scores
    max_score = max(scores.values())
    if max_score <= 0:
        return {k: 0.0 for k in scores}
    return {k: v / max_score for k, v in scores.items()}
