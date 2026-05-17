"""Rerank: TEI POST /rerank (один запрос ≤ max batch) или bi-encoder fallback через embeddings."""

from __future__ import annotations

import logging
import math

import httpx

from app.core.config import settings
from app.infrastructure.llm.clients.embedding_client import create_embeddings_batched

_log = logging.getLogger(__name__)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def rerank_texts(query: str, texts: list[str]) -> list[float]:
    """Scores в том же порядке, что и texts (выше = релевантнее)."""
    if not texts:
        return []
    prepared = [t.strip() for t in texts]
    if not any(prepared):
        return [0.0] * len(texts)

    tei_scores = await _try_tei_rerank(query, prepared)
    if tei_scores is not None:
        return tei_scores

    if settings.rag_rerank_bi_encoder_fallback:
        _log.warning(
            "TEI rerank не ответил (%s), fallback на bi-encoder %s",
            settings.rag_rerank_base_url or "(не задан)",
            settings.embedding_model_name,
        )
        return await _bi_encoder_scores(query, prepared)

    return [0.0] * len(texts)


async def _try_tei_rerank(query: str, texts: list[str]) -> list[float] | None:
    base = (settings.rag_rerank_base_url or "").strip().rstrip("/")
    if not base:
        return None

    max_batch = max(1, settings.rag_rerank_max_batch_size)
    if len(texts) > max_batch:
        _log.warning(
            "TEI rerank: обрезка %s → %s текстов (RAG_RERANK_MAX_BATCH_SIZE)",
            len(texts),
            max_batch,
        )
        texts = texts[:max_batch]

    url = f"{base}/rerank"
    payload: dict = {
        "query": query,
        "texts": texts,
        "truncate": True,
    }
    if settings.rag_rerank_model_name:
        payload["model"] = settings.rag_rerank_model_name

    try:
        async with httpx.AsyncClient(timeout=settings.rag_rerank_timeout_sec) as client:
            response = await client.post(url, json=payload)
        if response.status_code == 413:
            _log.warning(
                "TEI rerank HTTP 413: %s пар (лимит max-client-batch-size=%s)",
                len(texts),
                max_batch,
            )
            return None
        if response.status_code >= 400:
            _log.debug("TEI rerank HTTP %s: %s", response.status_code, response.text[:200])
            return None
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        _log.debug("TEI rerank unavailable: %s", exc)
        return None

    if not isinstance(data, list):
        return None

    scores = [0.0] * len(texts)
    for item in data:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        score = item.get("score")
        if isinstance(idx, int) and 0 <= idx < len(texts) and isinstance(score, (int, float)):
            scores[idx] = float(score)
    return scores


async def _bi_encoder_scores(query: str, texts: list[str]) -> list[float]:
    q_vectors = await create_embeddings_batched([query])
    if not q_vectors:
        return [0.0] * len(texts)
    q_vec = q_vectors[0]
    doc_vectors = await create_embeddings_batched(texts)
    if len(doc_vectors) != len(texts):
        return [0.0] * len(texts)
    return [_cosine_similarity(q_vec, vec) for vec in doc_vectors]
