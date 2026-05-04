"""Источники предсказаний (категории, теги и т.д.)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import PredictionSource
from app.seeds.util import rows_with_fresh_uuids

STANDARD_PREDICTION_SOURCES: list[dict[str, Any]] = [
    {"code": "manual", "name": "Ручной ввод", "description": None},
    {"code": "llm", "name": "Языковая модель", "description": None},
    {"code": "rule", "name": "Правило", "description": None},
    {"code": "import", "name": "Импорт", "description": None},
    {"code": "ensemble", "name": "Ансамбль", "description": None},
    {"code": "ocr", "name": "OCR", "description": None},
    {"code": "api", "name": "Внешний API", "description": None},
]


async def apply_prediction_sources_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_PREDICTION_SOURCES)
    stmt = insert(PredictionSource).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PredictionSource.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_PREDICTION_SOURCES)
