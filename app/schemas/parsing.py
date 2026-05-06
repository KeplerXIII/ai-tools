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
