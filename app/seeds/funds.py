"""Справочник фондов (типы доступа / классификации материалов)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Fund
from app.seeds.util import rows_with_fresh_uuids

STANDARD_FUNDS: list[dict[str, Any]] = [
    {
        "code": "news",
        "name": "Новостной фонд",
        "description": "Материалы новостного характера и оперативные сводки.",
    },
    {
        "code": "open",
        "name": "Открытый фонд",
        "description": "Открытые источники и данные, доступные без ограничения.",
    },
    {
        "code": "closed",
        "name": "Закрытый фонд",
        "description": "Ограниченный доступ; конфиденциальные или закрытые материалы.",
    },
]


async def apply_funds_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_FUNDS)
    stmt = insert(Fund).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Fund.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_FUNDS)
