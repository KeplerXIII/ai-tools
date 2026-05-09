from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EnqueueTranslateRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, max_length=10_000)
    target_lang: str = Field(default="ru", min_length=2, max_length=8)


class EnqueueTranslateResponse(BaseModel):
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


class EnqueueAnnotateRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, max_length=10_000)


class EnqueueAnnotateResponse(BaseModel):
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


class EnqueueCategorizeRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, max_length=10_000)


class EnqueueCategorizeResponse(BaseModel):
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


class EnqueueExtractorRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, max_length=10_000)


class EnqueueExtractorResponse(BaseModel):
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


class EnqueueTaggerRequest(BaseModel):
    document_ids: list[UUID] = Field(..., min_length=1, max_length=10_000)
    max_tags: int = Field(default=10, ge=1, le=100)


class EnqueueTaggerResponse(BaseModel):
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
