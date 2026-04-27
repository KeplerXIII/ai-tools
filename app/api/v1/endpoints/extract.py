from fastapi import APIRouter

from app.schemas.extract import (
    EntityExtractRequest,
    EntityExtractResponse,
    ExtractHtmlRequest,
    ExtractResponse,
    ExtractUrlRequest,
    SummaryRequest,
    SummaryResponse,
    TagRequest,
    TagResponse
)
from app.services.entity_extractor import extract_entities
from app.services.extractor import download_html, extract_article_text
from app.services.summarizer import summarize_text
from app.services.tagger import tag_text

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("/url", response_model=ExtractResponse)
def extract_from_url(payload: ExtractUrlRequest):
    html = download_html(str(payload.url))
    return extract_article_text(html, str(payload.url))


@router.post("/html", response_model=ExtractResponse)
def extract_from_html(payload: ExtractHtmlRequest):
    return extract_article_text(payload.html, payload.url)


@router.post("/entities", response_model=EntityExtractResponse)
def extract_article_entities(payload: EntityExtractRequest):
    return extract_entities(payload.text)


@router.post("/summary", response_model=SummaryResponse)
def summarize_article(payload: SummaryRequest):
    annotation = summarize_text(payload.text)
    return SummaryResponse(annotation=annotation)

@router.post("/tags", response_model=TagResponse)
def tag_article_text(payload: TagRequest):
    return tag_text(payload.text, payload.max_tags)