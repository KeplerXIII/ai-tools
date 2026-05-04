"""Справочник стран по ISO 3166-1 (alpha-2 + официальное англоязычное имя через pycountry)."""

from __future__ import annotations

from typing import Any

import pycountry
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Country
from app.seeds.util import rows_with_fresh_uuids


def _standard_countries_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in sorted(pycountry.countries, key=lambda x: x.alpha_2):
        # pycountry: alpha_2, name (English); пропускаем записи без alpha_2 на всякий случай
        code = getattr(c, "alpha_2", None)
        name = getattr(c, "name", None)
        if not code or not name:
            continue
        rows.append({"code": code, "name": name})
    return rows


STANDARD_COUNTRIES: list[dict[str, Any]] = _standard_countries_rows()


async def apply_countries_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_COUNTRIES)
    stmt = insert(Country).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Country.code],
        set_={"name": stmt.excluded.name},
    )
    await session.execute(stmt)
    return len(STANDARD_COUNTRIES)
