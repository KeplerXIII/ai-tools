from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.error_mapping import map_app_error
from app.domain.errors import AppError
from app.schemas.extract import (
    RefineSummaryRequest,
    RefineSummaryResponse,
    EntityExtractRequest,
    EntityExtractResponse,
    ExtractHtmlRequest,
    ExtractResponse,
    ExtractUrlRequest,
    SummaryRequest,
    SummaryResponse,
    TagRequest,
    TagResponse,
)
from app.services.entity_extractor import extract_entities
from app.services.extractor import download_html, extract_article_text
from app.services.summarizer import summarize_text, refine_summary
from app.services.tagger import tag_text

router = APIRouter(prefix="/extract", tags=["extract"])


def _safe_stream(generator):
    try:
        for chunk in generator:
            yield chunk
    except Exception as exc:
        # Streaming response is already started; return inline error chunk instead of crashing ASGI.
        yield f"\n[stream_error] {exc}"


@router.post("/url", response_model=ExtractResponse)
def extract_from_url(payload: ExtractUrlRequest):
    html = download_html(str(payload.url))
    return extract_article_text(html, str(payload.url))


@router.post("/html", response_model=ExtractResponse)
def extract_from_html(payload: ExtractHtmlRequest):
    return extract_article_text(payload.html, payload.url)


@router.post("/entities", response_model=EntityExtractResponse)
def extract_article_entities(payload: EntityExtractRequest):
    try:
        return extract_entities(payload.text)
    except AppError as exc:
        raise map_app_error(exc) from exc


@router.post("/summary", response_model=SummaryResponse)
def summarize_article(payload: SummaryRequest):
    try:
        annotation = summarize_text(payload.text)
    except AppError as exc:
        raise map_app_error(exc) from exc
    return SummaryResponse(annotation=annotation)


@router.post("/summary/stream")
def summarize_article_stream(payload: SummaryRequest):
    try:
        generator = summarize_text(
            text=payload.text,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream(generator),
        media_type="text/plain; charset=utf-8",
    )


@router.post("/tags", response_model=TagResponse)
def tag_article_text(payload: TagRequest):
    try:
        return tag_text(payload.text, payload.max_tags)
    except AppError as exc:
        raise map_app_error(exc) from exc


@router.post("/summary/refine", response_model=RefineSummaryResponse)
def refine_article_summary(payload: RefineSummaryRequest):
    try:
        refined_summary = refine_summary(
            article_text=payload.article_text,
            summary=payload.summary,
            user_instruction=payload.user_instruction,
            mode=payload.mode,
            stream=False,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return RefineSummaryResponse(refined_summary=refined_summary)


@router.post("/summary/refine/stream")
def refine_article_summary_stream(payload: RefineSummaryRequest):
    try:
        generator = refine_summary(
            article_text=payload.article_text,
            summary=payload.summary,
            user_instruction=payload.user_instruction,
            mode=payload.mode,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream(generator),
        media_type="text/plain; charset=utf-8",
    )