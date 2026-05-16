"""OpenAI-совместимый клиент embeddings (TEI: POST /v1/embeddings)."""

from __future__ import annotations

from functools import lru_cache

from openai import AsyncOpenAI, OpenAIError

from app.core.config import settings
from app.domain.errors import ExternalServiceError


@lru_cache(maxsize=1)
def _embedding_async_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.embedding_tei_base_url.rstrip("/"),
        api_key=settings.embedding_tei_api_key,
        timeout=settings.embedding_timeout_sec,
    )


async def create_embeddings(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    client = _embedding_async_client()
    try:
        response = await client.embeddings.create(
            model=settings.embedding_model_name,
            input=texts,
        )
    except OpenAIError as exc:
        raise ExternalServiceError(f"TEI embeddings: {exc}") from exc

    by_index = sorted(response.data, key=lambda row: row.index)
    return [row.embedding for row in by_index]
