import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.error_mapping import map_app_error
from app.api.streaming_utils import bytes_from_text_stream
from app.domain.errors import AppError, ValidationError
from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.llm.translator import detect_language, translate_text

router = APIRouter(prefix="/translate", tags=["translate"])


async def _safe_stream_bytes(stream):
    try:
        async for part in bytes_from_text_stream(stream):
            text = part.decode("utf-8", errors="replace")
            yield f"data: {text}\n\n".encode("utf-8")
        yield b"data: [DONE]\n\n"
    except Exception as exc:
        msg = str(exc).replace("\n", " ").strip()
        yield f"event: error\ndata: {msg}\n\n".encode("utf-8")


@router.post("", response_model=TranslateResponse)
async def translate(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    source_lang = await asyncio.to_thread(detect_language, payload.text)

    try:
        translation = await translate_text(
            text=payload.text,
            target_lang=payload.target_lang,
            stream=False,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    if not isinstance(translation, str):
        raise map_app_error(ValidationError("Некорректный ответ перевода"))

    return TranslateResponse(
        source_lang=source_lang,
        target_lang=payload.target_lang,
        translation=translation,
    )


@router.post("/stream")
async def translate_stream(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    source_lang = await asyncio.to_thread(detect_language, payload.text)

    try:
        stream = await translate_text(
            text=payload.text,
            target_lang=payload.target_lang,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream_bytes(stream),
        media_type="text/event-stream",
        headers={
            "X-Source-Lang": source_lang,
            "X-Target-Lang": payload.target_lang,
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
