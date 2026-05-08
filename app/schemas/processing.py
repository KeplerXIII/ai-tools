from __future__ import annotations

from typing import Literal

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


class EnqueueAnnotateMissingRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=10_000)


class EnqueueAnnotateMissingResponse(BaseModel):
    ok: bool = True
    batch_id: str
    queue: str
    scanned: int
    enqueued: int


class AnnotateBatchStatusResponse(BaseModel):
    ok: bool = True
    batch_id: str
    scanned: int
    enqueued: int
    completed: int
    failed: int
    skipped: int
    pending: int
    done: bool


class EnqueueCategorizeMissingRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=10_000)


class EnqueueCategorizeMissingResponse(BaseModel):
    ok: bool = True
    batch_id: str
    queue: str
    scanned: int
    enqueued: int


class CategorizeBatchStatusResponse(BaseModel):
    ok: bool = True
    batch_id: str
    scanned: int
    enqueued: int
    completed: int
    failed: int
    skipped: int
    pending: int
    done: bool


class EnqueueExtractorMissingRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=10_000)


class EnqueueExtractorMissingResponse(BaseModel):
    ok: bool = True
    batch_id: str
    queue: str
    scanned: int
    enqueued: int


class ExtractorBatchStatusResponse(BaseModel):
    ok: bool = True
    batch_id: str
    scanned: int
    enqueued: int
    completed: int
    failed: int
    skipped: int
    pending: int
    done: bool


class EnqueueTaggerMissingRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=10_000)
    max_tags: int = Field(default=10, ge=1, le=100)


class EnqueueTaggerMissingResponse(BaseModel):
    ok: bool = True
    batch_id: str
    queue: str
    scanned: int
    enqueued: int
    text_source: Literal["original", "translated"]


class TaggerBatchStatusResponse(BaseModel):
    ok: bool = True
    batch_id: str
    scanned: int
    enqueued: int
    completed: int
    failed: int
    skipped: int
    pending: int
    done: bool
