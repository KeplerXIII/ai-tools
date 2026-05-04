"""Корневые категории документов."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Category
from app.seeds.util import rows_with_fresh_uuids

STANDARD_CATEGORIES: list[dict[str, Any]] = [
    {
        "parent_id": None,
        "code": "defense",
        "name": "Оборона и ВПК",
        "description": None,
        "level": 0,
        "sort_order": 0,
        "is_active": True,
    },
    {
        "parent_id": None,
        "code": "procurement",
        "name": "Закупки и контракты",
        "description": None,
        "level": 0,
        "sort_order": 10,
        "is_active": True,
    },
    {
        "parent_id": None,
        "code": "technology",
        "name": "Технологии",
        "description": None,
        "level": 0,
        "sort_order": 20,
        "is_active": True,
    },
    {
        "parent_id": None,
        "code": "politics",
        "name": "Политика",
        "description": None,
        "level": 0,
        "sort_order": 30,
        "is_active": True,
    },
    {
        "parent_id": None,
        "code": "economy",
        "name": "Экономика",
        "description": None,
        "level": 0,
        "sort_order": 40,
        "is_active": True,
    },
]


async def apply_categories_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_CATEGORIES)
    stmt = insert(Category).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Category.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
            "level": stmt.excluded.level,
            "sort_order": stmt.excluded.sort_order,
            "is_active": stmt.excluded.is_active,
            "parent_id": stmt.excluded.parent_id,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_CATEGORIES)
