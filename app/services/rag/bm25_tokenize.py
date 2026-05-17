"""Токенизация для BM25-индекса (согласована с простым word-split, ru/en)."""

from __future__ import annotations

import re
from collections import Counter

_TOKEN_RE = re.compile(r"[\w\d]+", re.UNICODE)
_MIN_TERM_LEN = 2
_MAX_TERM_LEN = 128


def tokenize_for_bm25(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    terms: list[str] = []
    for match in _TOKEN_RE.finditer(text.lower()):
        term = match.group(0)
        if len(term) < _MIN_TERM_LEN:
            continue
        if len(term) > _MAX_TERM_LEN:
            term = term[:_MAX_TERM_LEN]
        terms.append(term)
    return terms


def term_frequencies(text: str) -> dict[str, int]:
    return dict(Counter(tokenize_for_bm25(text)))
