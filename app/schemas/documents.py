from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.schemas.extract import ExtractResponse, RefineSummaryMode


class DocumentEntityItem(BaseModel):
    id: uuid.UUID
    name: str


class DocumentExtractResponse(ExtractResponse):
    document_id: uuid.UUID
    from_cache: bool
    version: int = 1
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    translated_content: str | None = None
    original_summary: str | None = None
    translated_summary: str | None = None
    original_summary_stale: bool = False
    translated_summary_stale: bool = False
    statuses: list["DocumentStatusItem"] = []
    original_tags: list[str] = []
    translated_tags: list[str] = []
    entities_military_equipment: list[DocumentEntityItem] = []
    entities_manufacturers: list[DocumentEntityItem] = []
    entities_contracts: list[DocumentEntityItem] = []


class DocumentTranslateRequest(BaseModel):
    target_lang: str = Field(default="ru", min_length=2, max_length=8)


class DocumentTagRequest(BaseModel):
    max_tags: int = Field(default=12, ge=1, le=50)
    use_translation: bool = False


class DocumentEntitiesExtractResponse(BaseModel):
    ok: bool = True
    document_id: uuid.UUID
    military_equipment: list[DocumentEntityItem]
    manufacturers: list[DocumentEntityItem]
    contracts: list[DocumentEntityItem]


class DocumentEntityAssignRequest(BaseModel):
    entity_id: uuid.UUID


class DocumentStatusAssignRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class DocumentStatusItem(BaseModel):
    code: str
    name_ru: str
    description: str | None = None
    assigned_at: datetime
    assigned_by_id: uuid.UUID | None = None


class DocumentStatusCatalogItem(BaseModel):
    code: str
    name_ru: str
    description: str | None = None


class DocumentStatusesResponse(BaseModel):
    document_id: uuid.UUID
    statuses: list[DocumentStatusItem]


class SummarySource(str, Enum):
    original = "original"
    translated = "translated"


class DocumentSummaryRequest(BaseModel):
    source: SummarySource = SummarySource.original


class DocumentSummaryResponse(BaseModel):
    annotation: str
    document_id: uuid.UUID


class DocumentRefineSummaryRequest(BaseModel):
    source: SummarySource = SummarySource.original
    user_instruction: str = ""
    mode: RefineSummaryMode = RefineSummaryMode.add_context


class DocumentRefineSummaryResponse(BaseModel):
    refined_summary: str
    document_id: uuid.UUID


class DocumentUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=512)
    original_content: str | None = None
    translated_content: str | None = None

    @model_validator(mode="after")
    def at_least_one_field(self) -> DocumentUpdateRequest:
        if self.title is None and self.original_content is None and self.translated_content is None:
            raise ValueError("Укажите хотя бы одно поле: title, original_content или translated_content")
        return self


class ExtractUrlPersistRequest(BaseModel):
    url: HttpUrl
    document_type_code: str = "article"
