from fastapi import APIRouter

from app.schemas.extract import (
    ExtractHtmlRequest,
    ExtractResponse,
    ExtractUrlRequest,
)
from app.services.extractor import download_html, extract_article_text

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("/url", response_model=ExtractResponse)
def extract_from_url(payload: ExtractUrlRequest):
    html = download_html(str(payload.url))
    return extract_article_text(html, str(payload.url))


@router.post("/html", response_model=ExtractResponse)
def extract_from_html(payload: ExtractHtmlRequest):
    return extract_article_text(payload.html, payload.url)