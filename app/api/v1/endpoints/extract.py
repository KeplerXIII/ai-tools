from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.error_mapping import map_app_error
from app.api.streaming_utils import bytes_from_text_stream
from app.domain.errors import AppError, ValidationError
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
from app.services.llm.entity_extractor import extract_entities
from app.services.llm.summarizer import summarize_text, refine_summary
from app.services.llm.tagger import tag_text
from app.services.parsing.extractor import download_html, extract_article_text

router = APIRouter(prefix="/extract", tags=["extract"])


async def _safe_stream_bytes(stream):
    try:
        async for part in bytes_from_text_stream(stream):
            yield part
    except Exception as exc:
        yield f"\n[stream_error] {exc}\n".encode("utf-8")


@router.post("/url", response_model=ExtractResponse)
async def extract_from_url(payload: ExtractUrlRequest):
    html = await download_html(str(payload.url))
    return await extract_article_text(html, str(payload.url))


@router.post("/html", response_model=ExtractResponse)
async def extract_from_html(payload: ExtractHtmlRequest):
    return await extract_article_text(payload.html, payload.url)


@router.post("/entities", response_model=EntityExtractResponse)
async def extract_article_entities(payload: EntityExtractRequest):
    try:
        return await extract_entities(payload.text)
    except AppError as exc:
        raise map_app_error(exc) from exc


@router.post("/summary", response_model=SummaryResponse)
async def summarize_article(payload: SummaryRequest):
    try:
        annotation = await summarize_text(payload.text)
    except AppError as exc:
        raise map_app_error(exc) from exc
    if not isinstance(annotation, str):
        raise map_app_error(ValidationError("Некорректный ответ суммаризатора"))
    return SummaryResponse(annotation=annotation)


@router.post("/summary/stream")
async def summarize_article_stream(payload: SummaryRequest):
    try:
        stream = await summarize_text(
            text=payload.text,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream_bytes(stream),
        media_type="text/plain; charset=utf-8",
    )


@router.post("/tags", response_model=TagResponse)
async def tag_article_text(payload: TagRequest):
    try:
        result = await tag_text(payload.text, payload.max_tags)
    except AppError as exc:
        raise map_app_error(exc) from exc
    return TagResponse(tags=result.get("tags", []))


@router.post("/summary/refine", response_model=RefineSummaryResponse)
async def refine_article_summary(payload: RefineSummaryRequest):
    try:
        refined_summary = await refine_summary(
            article_text=payload.article_text,
            summary=payload.summary,
            user_instruction=payload.user_instruction,
            mode=payload.mode,
            stream=False,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    if not isinstance(refined_summary, str):
        raise map_app_error(ValidationError("Некорректный ответ уточнения аннотации"))
    return RefineSummaryResponse(refined_summary=refined_summary)


@router.post("/summary/refine/stream")
async def refine_article_summary_stream(payload: RefineSummaryRequest):
    try:
        stream = await refine_summary(
            article_text=payload.article_text,
            summary=payload.summary,
            user_instruction=payload.user_instruction,
            mode=payload.mode,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream_bytes(stream),
        media_type="text/plain; charset=utf-8",
    )
