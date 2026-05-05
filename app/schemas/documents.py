from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.schemas.extract import ExtractResponse, RefineSummaryMode


class DocumentExtractResponse(ExtractResponse):
    document_id: uuid.UUID
    from_cache: bool
    version: int = 1


class DocumentTranslateRequest(BaseModel):
    target_lang: str = Field(default="ru", min_length=2, max_length=8)


class DocumentTagRequest(BaseModel):
    max_tags: int = Field(default=12, ge=1, le=50)
    use_translation: bool = False


class DocumentStatusAssignRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class DocumentStatusItem(BaseModel):
    code: str
    name_ru: str
    description: str | None = None
    assigned_at: datetime
    assigned_by_id: uuid.UUID | None = None


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
