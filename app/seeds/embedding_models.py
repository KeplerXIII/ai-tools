"""Модели эмбеддингов для векторного поиска."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import EmbeddingModel
from app.seeds.util import rows_with_fresh_uuids

STANDARD_EMBEDDING_MODELS: list[dict[str, Any]] = [
    {
        "name": "bge-m3",
        "dimension": 1024,
        "provider": "tei",
        "description": "BAAI bge-m3; столбец document_embeddings.embedding = vector(1024)",
    },
]


async def apply_embedding_models_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_EMBEDDING_MODELS)
    stmt = insert(EmbeddingModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[EmbeddingModel.name],
        set_={
            "dimension": stmt.excluded.dimension,
            "provider": stmt.excluded.provider,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_EMBEDDING_MODELS)
