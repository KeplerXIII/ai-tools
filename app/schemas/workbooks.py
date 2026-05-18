from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


class WorkbookCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)


class WorkbookUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    notes: str | None = None
    generation_prompt: str | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> WorkbookUpdateRequest:
        if self.name is None and self.notes is None and self.generation_prompt is None:
            raise ValueError("Укажите хотя бы одно поле: name, notes или generation_prompt")
        return self


class WorkbookListItem(BaseModel):
    workbook_id: uuid.UUID
    name: str
    sources_count: int = 0
    entries_count: int = 0
    created_at: datetime
    updated_at: datetime


class WorkbookListResponse(BaseModel):
    total: int
    items: list[WorkbookListItem]


class WorkbookSourceItem(BaseModel):
    document_id: uuid.UUID
    title: str
    translated_title: str | None = None
    source_url: str | None = None
    document_type_code: str
    document_type_name: str
    excerpt: str | None = None
    added_at: datetime


class WorkbookEntryItem(BaseModel):
    entry_id: uuid.UUID
    content: str
    sources: list[WorkbookSourceItem] = []
    created_at: datetime
    updated_at: datetime


class WorkbookEntryCreateRequest(BaseModel):
    content: str = Field(..., min_length=1)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    excerpts: dict[str, str] = Field(
        default_factory=dict,
        description="document_id (str) → выдержка; для вставки фрагмента из редактора",
    )

    @field_validator("document_ids")
    @classmethod
    def _unique_document_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(value))


class WorkbookEntryUpdateRequest(BaseModel):
    content: str | None = Field(default=None, min_length=1)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)

    @field_validator("document_ids")
    @classmethod
    def _unique_document_ids(cls, value: list[uuid.UUID] | None) -> list[uuid.UUID] | None:
        if value is None:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _at_least_one_field(self) -> WorkbookEntryUpdateRequest:
        if self.content is None and self.document_ids is None:
            raise ValueError("Укажите content и/или document_ids")
        return self


class WorkbookEntrySourcesAddRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=50)
    excerpts: dict[str, str] = Field(default_factory=dict)

    @field_validator("document_ids")
    @classmethod
    def _unique_document_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return list(dict.fromkeys(value))


class WorkbookDetailResponse(BaseModel):
    workbook_id: uuid.UUID
    name: str
    notes: str | None = None
    generation_prompt: str | None = None
    entries: list[WorkbookEntryItem] = []
    created_at: datetime
    updated_at: datetime


# Устаревшие схемы уровня тетради (оставлены для совместимости API)
class WorkbookDocumentItem(WorkbookSourceItem):
    pass


class WorkbookDocumentsAddRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)

    @field_validator("document_ids")
    @classmethod
    def _unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        unique = list(dict.fromkeys(value))
        if len(unique) != len(value):
            raise ValueError("document_ids не должны повторяться")
        return unique


class WorkbookDocumentsAddResponse(BaseModel):
    added: int
    skipped: int
    documents: list[WorkbookDocumentItem]
