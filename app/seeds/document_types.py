"""Стандартные типы документов (код, название, комментарий).

Используются CLI ``seed_document_types`` и оркестратор ``seed_reference_data``.
Первичный ключ
при заливке генерируется в сиде (``uuid.uuid4``), без фиксированных идентификаторов.
"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DocumentType
from app.seeds.util import rows_with_fresh_uuids


class DocumentTypeSeed(TypedDict):
    code: str
    name: str
    description: str


STANDARD_DOCUMENT_TYPES: list[DocumentTypeSeed] = [
    {
        "code": "undefined",
        "name": "Неопределён",
        "description": "Тип документа не был передан источником",
    },
    {"code": "news", "name": "Новость", "description": "Краткое сообщение о событии"},
    {
        "code": "article",
        "name": "Статья",
        "description": "Авторский или редакционный материал шире новости",
    },
    {
        "code": "report",
        "name": "Отчёт",
        "description": "Документ с результатами наблюдения, исследования, работы",
    },
    {
        "code": "analysis",
        "name": "Аналитический материал",
        "description": "Разбор ситуации, причин, последствий, тенденций",
    },
    {
        "code": "analytical_note",
        "name": "Аналитическая справка",
        "description": "Краткая структурированная справка для принятия решений",
    },
    {
        "code": "briefing",
        "name": "Сводка",
        "description": "Краткое оперативное изложение нескольких фактов",
    },
    {
        "code": "review",
        "name": "Обзор",
        "description": "Обзор темы, рынка, отрасли, событий за период",
    },
    {
        "code": "research",
        "name": "Исследование",
        "description": "Более глубокий исследовательский материал",
    },
    {
        "code": "press_release",
        "name": "Пресс-релиз",
        "description": "Официальное сообщение организации",
    },
    {
        "code": "interview",
        "name": "Интервью",
        "description": "Материал в формате вопросов и ответов",
    },
    {
        "code": "statement",
        "name": "Заявление",
        "description": "Официальная позиция лица или организации",
    },
    {
        "code": "regulatory_document",
        "name": "Нормативный документ",
        "description": "Закон, приказ, постановление, регламент",
    },
    {
        "code": "technical_document",
        "name": "Технический документ",
        "description": "ТТХ, спецификация, руководство, описание системы",
    },
    {
        "code": "contract_notice",
        "name": "Закупка / контрактное сообщение",
        "description": "Тендер, контракт, уведомление о закупке",
    },
    {"code": "other", "name": "Другое", "description": "Резервный тип"},
]


async def apply_document_types_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids([dict(item) for item in STANDARD_DOCUMENT_TYPES])
    stmt = insert(DocumentType).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DocumentType.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(rows)
