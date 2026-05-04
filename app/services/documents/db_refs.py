import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import DocumentType, EntityType, Language, PredictionSource


async def prediction_source_id(session: AsyncSession, code: str) -> uuid.UUID:
    q = await session.execute(select(PredictionSource.id).where(PredictionSource.code == code))
    return q.scalar_one()


async def language_id_by_code(session: AsyncSession, code: str) -> uuid.UUID:
    q = await session.execute(select(Language.id).where(Language.code == code))
    row = q.scalar_one_or_none()
    if row is None:
        q2 = await session.execute(select(Language.id).where(Language.code == "en"))
        return q2.scalar_one()
    return row


async def document_type_id_by_code(session: AsyncSession, code: str) -> uuid.UUID:
    q = await session.execute(select(DocumentType.id).where(DocumentType.code == code))
    return q.scalar_one()


async def entity_type_id_by_code(session: AsyncSession, code: str) -> uuid.UUID:
    q = await session.execute(select(EntityType.id).where(EntityType.code == code))
    return q.scalar_one()
