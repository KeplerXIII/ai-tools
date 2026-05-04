"""Справочник сред (операционных окружений) для документов."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Environment
from app.seeds.util import rows_with_fresh_uuids

STANDARD_ENVIRONMENTS: list[dict[str, Any]] = [
    {
        "code": "underwater",
        "name": "Подводная среда",
        "description": "Подводные операции, объекты и среда.",
    },
    {
        "code": "surface_water",
        "name": "Надводная среда",
        "description": "Надводные платформы, морская поверхность и прибрежная зона.",
    },
    {
        "code": "underground",
        "name": "Подземная среда",
        "description": "Подземные сооружения, туннели, шахты и среда под поверхностью суши.",
    },
    {
        "code": "above_ground",
        "name": "Надземная среда",
        "description": "Наземная поверхность, надземные объекты и инфраструктура.",
    },
    {
        "code": "air",
        "name": "Воздушная среда",
        "description": "Атмосфера, авиация и воздушное пространство.",
    },
    {
        "code": "space",
        "name": "Космическая среда",
        "description": "Околоземное и дальнее космическое пространство.",
    },
    {
        "code": "cyber",
        "name": "Кибернетическая среда",
        "description": "Информационно-телекоммуникационные сети и киберпространство.",
    },
    {
        "code": "intergalactic",
        "name": "Межгалактическая среда",
        "description": "Межгалактическое пространство и среда за пределами галактики.",
    },
]


async def apply_environments_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_ENVIRONMENTS)
    stmt = insert(Environment).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Environment.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_ENVIRONMENTS)
