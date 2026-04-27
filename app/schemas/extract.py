from pydantic import BaseModel, HttpUrl


class ExtractUrlRequest(BaseModel):
    url: HttpUrl


class ExtractHtmlRequest(BaseModel):
    html: str
    url: str | None = None


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