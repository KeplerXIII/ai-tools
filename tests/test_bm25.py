from __future__ import annotations

import uuid

from app.services.rag.bm25_scoring import bm25_score_document, normalize_bm25_scores
from app.services.rag.bm25_tokenize import term_frequencies, tokenize_for_bm25


def test_tokenize_russian_and_numbers() -> None:
    terms = tokenize_for_bm25("Сбербанк купил 10% акций Tesla")
    assert "сбербанк" in terms
    assert "10" in terms or "акций" in terms


def test_bm25_prefers_matching_document() -> None:
    query = tokenize_for_bm25("сбербанк прибыль")
    term_df = {"сбербанк": 2, "прибыль": 2, "tesla": 1}
    corpus_size = 3
    avg_dl = 4.0

    relevant = bm25_score_document(
        query,
        term_tf=term_frequencies("сбербанк показал прибыль"),
        doc_length=3,
        term_df=term_df,
        corpus_size=corpus_size,
        avg_doc_length=avg_dl,
    )
    noise = bm25_score_document(
        query,
        term_tf=term_frequencies("tesla электромобили"),
        doc_length=2,
        term_df=term_df,
        corpus_size=corpus_size,
        avg_doc_length=avg_dl,
    )
    assert relevant > noise


def test_normalize_bm25_scores() -> None:
    cid = uuid.uuid4()
    out = normalize_bm25_scores({cid: 4.0})
    assert out[cid] == 1.0
