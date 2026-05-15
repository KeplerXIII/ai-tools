from __future__ import annotations

import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.services.parsing.discovery_paths import MAX_DISCOVERY_PATHS, normalize_discovery_paths
from app.services.parsing.rss_urls import MAX_RSS_URLS, normalize_rss_urls


class SourceCreateRequest(BaseModel):
    url: HttpUrl
    name: str | None = Field(default=None, max_length=255)
    language_code: str = Field(default="en", min_length=2, max_length=8)
    country_code: str | None = Field(default=None, min_length=2, max_length=8)
    rss_url: HttpUrl | None = Field(default=None, description="Устаревшее: один RSS; используйте rss_urls")
    rss_urls: list[str] = Field(
        default_factory=list,
        max_length=MAX_RSS_URLS,
        description="URL RSS/Atom-фидов (несколько фидов объединяются при разборе).",
    )
    discovery_paths: list[str] = Field(
        default_factory=list,
        max_length=MAX_DISCOVERY_PATHS,
        description=(
            "Пути от корня сайта для HTML-обхода, например /news и /news/newsreleases. "
            "Главная — только при явном /. Пустой список — без HTML-обхода (только RSS)."
        ),
    )
    document_type_code: str = Field(
        min_length=1,
        max_length=64,
        description="Код типа документа из справочника; при разборе источника документы создаются с этим типом.",
    )

    @field_validator("discovery_paths", mode="before")
    @classmethod
    def _normalize_discovery_paths(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise TypeError("discovery_paths must be a list of strings")
        return normalize_discovery_paths([str(p) for p in value])

    @field_validator("rss_urls", mode="before")
    @classmethod
    def _normalize_rss_urls_field(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise TypeError("rss_urls must be a list of strings")
        return normalize_rss_urls([str(u) for u in value])

    @model_validator(mode="before")
    @classmethod
    def _merge_legacy_rss_url(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        rss_urls = data.get("rss_urls")
        rss_url = data.get("rss_url")
        if (not rss_urls) and rss_url:
            data = {**data, "rss_urls": [rss_url]}
        return data


class SourceCreateResponse(BaseModel):
    source_id: uuid.UUID
    url: str
    name: str | None = None
    language_code: str
    country_code: str | None = None
    rss_url: str | None = None
    rss_urls: list[str] = Field(default_factory=list)
    discovery_paths: list[str] = Field(default_factory=list)
    is_active: bool
    document_type_code: str
    document_type_name: str


class SourceUpdateRequest(BaseModel):
    """Тело PATCH /parsing/sources/{source_id} — те же поля, что при создании."""

    url: HttpUrl
    name: str | None = Field(default=None, max_length=255)
    language_code: str = Field(default="en", min_length=2, max_length=8)
    country_code: str | None = Field(default=None, min_length=2, max_length=8)
    rss_url: HttpUrl | None = Field(default=None, description="Устаревшее: один RSS; используйте rss_urls")
    rss_urls: list[str] = Field(
        default_factory=list,
        max_length=MAX_RSS_URLS,
        description="URL RSS/Atom-фидов.",
    )
    discovery_paths: list[str] = Field(
        default_factory=list,
        max_length=MAX_DISCOVERY_PATHS,
        description=(
            "Пути от корня сайта для HTML-обхода. Главная — только при явном /. "
            "Пустой список — без HTML-обхода (только RSS)."
        ),
    )
    document_type_code: str = Field(min_length=1, max_length=64)

    @field_validator("discovery_paths", mode="before")
    @classmethod
    def _normalize_discovery_paths_update(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise TypeError("discovery_paths must be a list of strings")
        return normalize_discovery_paths([str(p) for p in value])

    @field_validator("rss_urls", mode="before")
    @classmethod
    def _normalize_rss_urls_field_update(cls, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            raise TypeError("rss_urls must be a list of strings")
        return normalize_rss_urls([str(u) for u in value])

    @model_validator(mode="before")
    @classmethod
    def _merge_legacy_rss_url_update(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        rss_urls = data.get("rss_urls")
        rss_url = data.get("rss_url")
        if (not rss_urls) and rss_url:
            data = {**data, "rss_urls": [rss_url]}
        return data


SourceUpdateResponse = SourceCreateResponse


class PostParseProcessingOptions(BaseModel):
    """Фоновая обработка после успешного разбора источника.

    При ``full_llm_pipeline=True`` остальные флаги игнорируются (умный сквозной пайплайн).

    При гранулярных флагах без полного пайплайна независимые шаги (оригинал, перевод как таковой, сущности) ставятся
    батчами; тегирование по переводу, аннотация по переводу и категоризация **в связке с** ``llm_translate`` ставятся
    только после успешного сохранения перевода. Категоризация **без** ``llm_translate`` идёт сразу по правилам модели:
    есть перевод в БД — по нему, иначе по оригиналу.
    """

    full_llm_pipeline: bool = Field(
        default=False,
        description="Умный полный LLM-пайплайн для новых документов (как POST .../full-llm-pipeline)",
    )
    llm_tag_original: bool = Field(default=False, description="Теги по языку оригинала")
    llm_translate: bool = Field(default=False, description="Перевод на target_lang")
    llm_extractor: bool = Field(default=False, description="Извлечение сущностей")
    llm_tag_translated: bool = Field(default=False, description="Теги по тексту перевода")
    llm_annotate: bool = Field(default=False, description="Аннотация (summary по переводу)")
    llm_categorize: bool = Field(
        default=False,
        description=(
            "Без llm_translate: категоризация сразу (перевод в БД, если есть, иначе оригинал). "
            "С llm_translate: только после успешного перевода, по переводу"
        ),
    )
    target_lang: str = Field(default="ru", min_length=2, max_length=8)
    max_tags: int = Field(default=10, ge=1, le=100)


class ParseSourceRequest(BaseModel):
    source_id: uuid.UUID
    days: int = Field(default=3, ge=1, le=30)
    skip_undated: bool = Field(
        default=True,
        description=(
            "После извлечения не сохранять документ, если итоговая дата публикации неизвестна."
        ),
    )
    post_parse: PostParseProcessingOptions | None = Field(
        default=None,
        description="Опционально: что запустить после успешного разбора для созданных документов",
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
    rss_urls: list[str] = Field(default_factory=list)
    discovery_paths: list[str] = Field(default_factory=list)
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
