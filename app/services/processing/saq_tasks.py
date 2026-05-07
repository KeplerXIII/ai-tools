from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError

from app.domain.errors import NotFoundError
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.documents.document_pipeline import run_translate_document
from app.services.processing.translate_batch_store import inc_translate_batch_counter


async def translate_document_job(
    ctx: dict,
    *,
    document_id: str,
    target_lang: str = "ru",
    started_by_id: str | None = None,
    batch_id: str | None = None,
) -> dict[str, str]:
    parsed_document_id = uuid.UUID(document_id)
    parsed_started_by = uuid.UUID(started_by_id) if started_by_id else None

    async with AsyncSessionLocal() as session:
        try:
            await run_translate_document(
                session,
                document_id=parsed_document_id,
                target_lang=target_lang,
                started_by_id=parsed_started_by,
            )
            await session.commit()
        except NotFoundError:
            # The document may be deleted after enqueue and before processing.
            await session.rollback()
            if batch_id:
                await inc_translate_batch_counter(batch_id, "skipped")
            return {
                "document_id": document_id,
                "status": "skipped_not_found",
            }
        except IntegrityError as exc:
            # FK violation on processing_jobs.document_id can happen in delete races.
            await session.rollback()
            if "processing_jobs_document_id_fkey" in str(exc):
                if batch_id:
                    await inc_translate_batch_counter(batch_id, "skipped")
                return {
                    "document_id": document_id,
                    "status": "skipped_not_found",
                }
            raise
        except Exception:
            await session.rollback()
            if batch_id:
                await inc_translate_batch_counter(batch_id, "failed")
            raise

    if batch_id:
        await inc_translate_batch_counter(batch_id, "completed")
    return {
        "document_id": document_id,
        "status": "translated",
    }
