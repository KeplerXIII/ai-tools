from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class SourceCreateRequest(BaseModel):
    url: HttpUrl
    name: str | None = Field(default=None, max_length=255)
    language_code: str = Field(default="en", min_length=2, max_length=8)
    country_code: str | None = Field(default=None, min_length=2, max_length=8)
    rss_url: HttpUrl | None = None


class SourceCreateResponse(BaseModel):
    source_id: uuid.UUID
    url: str
    name: str | None = None
    language_code: str
    country_code: str | None = None
    rss_url: str | None = None
    is_active: bool


class ParseSourceRequest(BaseModel):
    source_id: uuid.UUID
    days: int = Field(default=3, ge=1, le=30)
    document_type_code: str = "undefined"


class ParseSourceDocumentItem(BaseModel):
    document_id: uuid.UUID
    title: str
    source_url: str | None = None
    published_at: datetime | None = None
    created_at: datetime


class ParseSourceResponse(BaseModel):
    source_id: uuid.UUID
    found_total: int
    created_total: int
    existing_unprocessed_by_source: list[ParseSourceDocumentItem]
    new_unprocessed_by_source: list[ParseSourceDocumentItem]
