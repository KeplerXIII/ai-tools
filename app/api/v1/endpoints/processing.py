from __future__ import annotations

import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_started_by_id
from app.core.config import settings
from app.infrastructure.db.models import Document
from app.infrastructure.db.session import get_db
from app.schemas.processing import (
    EnqueueTranslateMissingRequest,
    EnqueueTranslateMissingResponse,
    TranslateBatchStatusResponse,
)
from app.services.processing.saq_queue import get_saq_queue
from app.services.processing.translate_batch_store import (
    get_translate_batch,
    inc_translate_batch_counter,
    init_translate_batch,
)

router = APIRouter(prefix="/processing", tags=["processing"])


@router.post("/documents/translate-missing", response_model=EnqueueTranslateMissingResponse)
async def enqueue_translate_missing_documents(
    payload: EnqueueTranslateMissingRequest,
    db: AsyncSession = Depends(get_db),
    started_by_id: UUID | None = Depends(get_optional_started_by_id),
) -> EnqueueTranslateMissingResponse:
    q = (
        select(Document.id)
        .where(
            or_(
                Document.translated_content.is_(None),
                Document.translated_content == "",
                func.btrim(Document.translated_content) == "",
            ),
        )
        .order_by(Document.created_at.asc())
    )
    if payload.limit is not None:
        q = q.limit(payload.limit)
    rows = await db.execute(q)
    document_ids = [str(row.id) for row in rows]
    batch_id = str(uuid.uuid4())
    await init_translate_batch(batch_id, scanned=len(document_ids))

    queue = get_saq_queue()
    await queue.connect()
    try:
        enqueued = 0
        started_by = str(started_by_id) if started_by_id else None
        for document_id in document_ids:
            job = await queue.enqueue(
                "translate_document_job",
                key=f"translate-missing:{document_id}",
                document_id=document_id,
                target_lang=payload.target_lang,
                started_by_id=started_by,
                batch_id=batch_id,
                timeout=settings.saq_translate_job_timeout_sec,
            )
            if job is not None:
                enqueued += 1
                await inc_translate_batch_counter(batch_id, "enqueued")
    finally:
        await queue.disconnect()

    return EnqueueTranslateMissingResponse(
        batch_id=batch_id,
        queue=queue.name,
        scanned=len(document_ids),
        enqueued=enqueued,
    )


@router.get("/documents/translate-missing/{batch_id}", response_model=TranslateBatchStatusResponse)
async def get_translate_missing_batch_status(batch_id: str) -> TranslateBatchStatusResponse:
    payload = await get_translate_batch(batch_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Батч не найден")

    enqueued = payload["enqueued"]
    completed = payload["completed"]
    failed = payload["failed"]
    skipped = payload["skipped"]
    finished = completed + failed + skipped
    pending = max(0, enqueued - finished)
    done = enqueued == 0 or pending == 0

    return TranslateBatchStatusResponse(
        batch_id=batch_id,
        scanned=payload["scanned"],
        enqueued=enqueued,
        completed=completed,
        failed=failed,
        skipped=skipped,
        pending=pending,
        done=done,
    )
