"""Категории оборонной тематики (Jane's-style taxonomy, см. ``defense_taxonomy``)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Category
from app.seeds.defense_taxonomy import DEFENSE_CATEGORY_TAXONOMY

_FALLBACK_CATEGORIES: tuple[dict[str, object], ...] = (
    {
        "code": "other_domain",
        "name": "Other domain",
        "name_ru": "Другое",
        "description": "Documents outside of the current defense taxonomy scope.",
        "description_ru": "Материалы вне предметной области текущей таксономии.",
        "level": 1,
        "parent_code": None,
    },
)


async def apply_categories_seed(session: AsyncSession) -> int:
    tax = sorted([*DEFENSE_CATEGORY_TAXONOMY, *_FALLBACK_CATEGORIES], key=lambda x: (x["level"], x["code"]))
    res = await session.execute(select(Category.code, Category.id))
    id_by_code: dict[str, uuid.UUID] = {row[0]: row[1] for row in res.all()}

    for i, item in enumerate(tax):
        parent_code = item.get("parent_code")
        parent_id = id_by_code.get(parent_code) if parent_code else None
        row = {
            "id": uuid.uuid4(),
            "code": item["code"],
            "name": item["name"],
            "name_ru": item["name_ru"],
            "description": item.get("description"),
            "description_ru": item.get("description_ru"),
            "level": item["level"],
            "sort_order": i * 10,
            "is_active": True,
            "parent_id": parent_id,
        }
        stmt = insert(Category).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=[Category.code],
            set_={
                "name": stmt.excluded.name,
                "name_ru": stmt.excluded.name_ru,
                "description": stmt.excluded.description,
                "description_ru": stmt.excluded.description_ru,
                "level": stmt.excluded.level,
                "sort_order": stmt.excluded.sort_order,
                "is_active": stmt.excluded.is_active,
                "parent_id": stmt.excluded.parent_id,
            },
        )
        await session.execute(stmt)
        cid = await session.scalar(select(Category.id).where(Category.code == item["code"]))
        if cid is not None:
            id_by_code[item["code"]] = cid

    return len(tax)
