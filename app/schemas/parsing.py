from __future__ import annotations

import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


class SourceCreateRequest(BaseModel):
    url: HttpUrl
    name: str | None = Field(default=None, max_length=255)
    language_code: str = Field(default="en", min_length=2, max_length=8)
    country_code: str | None = Field(default=None, min_length=2, max_length=8)
    rss_url: HttpUrl | None = None
    document_type_code: str = Field(
        min_length=1,
        max_length=64,
        description="Код типа документа из справочника; при разборе источника документы создаются с этим типом.",
    )


class SourceCreateResponse(BaseModel):
    source_id: uuid.UUID
    url: str
    name: str | None = None
    language_code: str
    country_code: str | None = None
    rss_url: str | None = None
    is_active: bool
    document_type_code: str
    document_type_name: str


class ParseSourceRequest(BaseModel):
    source_id: uuid.UUID
    days: int = Field(default=3, ge=1, le=30)
    skip_undated: bool = Field(
        default=True,
        description=(
            "После извлечения не сохранять документ, если итоговая дата публикации неизвестна."
        ),
    )


class ParseSourceDocumentItem(BaseModel):
    document_id: uuid.UUID
    title: str
    source_url: str | None = None
    published_at: datetime | None = None
    created_at: datetime


class ParseSourceEnqueueResponse(BaseModel):
    parse_run_id: uuid.UUID
    source_id: uuid.UUID
    processing_job_id: uuid.UUID | None = None
    status: Literal["pending"] = "pending"


class ParseSourceRunResponse(BaseModel):
    parse_run_id: uuid.UUID
    source_id: uuid.UUID
    processing_job_id: uuid.UUID | None = None
    phase: str | None = None
    status: Literal["pending", "running", "completed", "failed"]
    found_total: int | None = None
    created_total: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    existing_unprocessed_by_source: list[ParseSourceDocumentItem] = Field(default_factory=list)
    new_unprocessed_by_source: list[ParseSourceDocumentItem] = Field(default_factory=list)


class SourceListItem(BaseModel):
    source_id: uuid.UUID
    name: str | None = None
    url: str
    rss_url: str | None = None
    language_code: str
    country_code: str | None = None
    document_type_code: str
    document_type_name: str
    is_active: bool
    created_at: datetime
    added_by_user_id: uuid.UUID
    added_by_username: str
    documents_total: int = 0
    documents_unprocessed: int = 0
    last_parse_created_total: int | None = None
    last_parse_at: datetime | None = None


class SourceListResponse(BaseModel):
    total: int
    items: list[SourceListItem]
    can_filter_by_all_users: bool = False


class ActiveParseRunItem(BaseModel):
    """Источник с незавершённым запуском разбора (для восстановления UI без локального хранилища)."""

    source_id: uuid.UUID
    parse_run: ParseSourceRunResponse


class ActiveParseRunsResponse(BaseModel):
    items: list[ActiveParseRunItem]


class LanguageCatalogItem(BaseModel):
    """Строка справочника ``languages`` (код и отображаемое имя)."""

    code: str
    name: str

    model_config = {"from_attributes": True}


class CountryCatalogItem(BaseModel):
    """Строка справочника ``countries`` (код и отображаемое имя)."""

    code: str
    name: str

    model_config = {"from_attributes": True}
