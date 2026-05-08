from __future__ import annotations

from pydantic import BaseModel, Field


class EnqueueTranslateMissingRequest(BaseModel):
    target_lang: str = Field(default="ru", min_length=2, max_length=8)
    limit: int | None = Field(default=None, ge=1, le=10_000)


class EnqueueTranslateMissingResponse(BaseModel):
    ok: bool = True
    batch_id: str
    queue: str
    scanned: int
    enqueued: int


class TranslateBatchStatusResponse(BaseModel):
    ok: bool = True
    batch_id: str
    scanned: int
    enqueued: int
    completed: int
    failed: int
    skipped: int
    pending: int
    done: bool
