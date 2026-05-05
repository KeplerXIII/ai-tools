"""Справочник статусов документов (код, имя на русском, описание)."""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DocumentStatus
from app.seeds.util import rows_with_fresh_uuids


class DocumentStatusSeed(TypedDict):
    code: str
    name_ru: str
    description: str


STANDARD_DOCUMENT_STATUSES: list[DocumentStatusSeed] = [
    {
        "code": "unprocessed",
        "name_ru": "Необработанный",
        "description": "Документ ещё не прошёл обработку.",
    },
    {
        "code": "processed",
        "name_ru": "Обработанный",
        "description": "Документ успешно обработан.",
    },
    {
        "code": "new",
        "name_ru": "Новый",
        "description": "Новый документ, недавно добавлен в систему.",
    },
    {
        "code": "published",
        "name_ru": "Опубликованный",
        "description": "Документ опубликован и доступен для просмотра.",
    },
    {
        "code": "important",
        "name_ru": "Важный",
        "description": "Документ отмечен как приоритетный.",
    },
    {
        "code": "not_interesting",
        "name_ru": "Не интересно",
        "description": "Документ помечен как не представляющий интереса.",
    },
]


async def apply_document_statuses_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids([dict(item) for item in STANDARD_DOCUMENT_STATUSES])
    stmt = insert(DocumentStatus).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DocumentStatus.code],
        set_={
            "name_ru": stmt.excluded.name_ru,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(rows)
