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