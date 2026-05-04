"""Типы сущностей для извлечения из документов."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import EntityType
from app.seeds.util import rows_with_fresh_uuids

STANDARD_ENTITY_TYPES: list[dict[str, Any]] = [
    {
        "code": "military_equipment",
        "name": "Вооружение и техника",
        "description": None,
    },
    {"code": "manufacturer", "name": "Производитель", "description": None},
    {"code": "contract", "name": "Контракт / сделка", "description": None},
]


async def apply_entity_types_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_ENTITY_TYPES)
    stmt = insert(EntityType).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[EntityType.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_ENTITY_TYPES)
