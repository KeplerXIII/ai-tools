from pydantic import BaseModel, HttpUrl, Field
from enum import Enum


class ExtractUrlRequest(BaseModel):
    url: HttpUrl


class ExtractHtmlRequest(BaseModel):
    html: str
    url: str | None = None


class ImageInfo(BaseModel):
    url: str
    alt: str | None = None
    title: str | None = None


class ExtractResponse(BaseModel):
    title: str | None = None
    author: str | None = None
    date: str | None = None
    url: str | None = None
    text: str
    length: int
    method: str
    quality: str
    needs_review: bool
    images: list[ImageInfo] = []
    main_image: str | None = None


class EntityExtractRequest(BaseModel):
    text: str


class EntityExtractResponse(BaseModel):
    military_equipment: list[str]
    manufacturers: list[str]
    contracts: list[str]


class SummaryRequest(BaseModel):
    text: str


class SummaryResponse(BaseModel):
    annotation: str


class TagRequest(BaseModel):
    text: str
    max_tags: int = 12


class TagResponse(BaseModel):
    tags: list[str]


class RefineSummaryMode(str, Enum):
    shorten = "shorten"
    expand = "expand"
    add_context = "add_context"


class RefineSummaryRequest(BaseModel):
    article_text: str = Field(..., min_length=1)
    summary: str = Field(..., min_length=1)
    user_instruction: str = ""
    mode: RefineSummaryMode = RefineSummaryMode.add_context


class RefineSummaryResponse(BaseModel):
    refined_summary: str