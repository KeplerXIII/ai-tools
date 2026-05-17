"""Контракт backend'а поиска (vector, lexical, …)."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag.types import RetrievalFilters, RetrievedChunk


class RetrievalBackend(Protocol):
    name: str

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str,
        query_vector: list[float],
        fetch_k: int,
        chunk_types: tuple[str, ...],
        filters: RetrievalFilters,
    ) -> list[RetrievedChunk]:
        ...
