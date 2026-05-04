"""Языки контента."""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Language
from app.seeds.util import rows_with_fresh_uuids

STANDARD_LANGUAGES: list[dict[str, Any]] = [
    {"code": "en", "name": "English"},
    {"code": "ru", "name": "Russian"},
    {"code": "de", "name": "German"},
    {"code": "ar", "name": "Arabic"},
    {"code": "it", "name": "Italian"},
    {"code": "es", "name": "Spanish"},
]


async def apply_languages_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_LANGUAGES)
    stmt = insert(Language).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Language.code],
        set_={"name": stmt.excluded.name},
    )
    await session.execute(stmt)
    return len(STANDARD_LANGUAGES)
