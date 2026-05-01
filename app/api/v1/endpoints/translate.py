from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.api.error_mapping import map_app_error
from app.domain.errors import AppError
from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.translator import detect_language, translate_text

router = APIRouter(prefix="/translate", tags=["translate"])


def _safe_stream(generator):
    try:
        for chunk in generator:
            yield chunk
    except Exception as exc:
        # Streaming response is already started; return inline error chunk instead of crashing ASGI.
        yield f"\n[stream_error] {exc}"


@router.post("", response_model=TranslateResponse)
def translate(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    source_lang = detect_language(payload.text)

    try:
        translation = translate_text(
            text=payload.text,
            target_lang=payload.target_lang,
            stream=False,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return TranslateResponse(
        source_lang=source_lang,
        target_lang=payload.target_lang,
        translation=translation,
    )


@router.post("/stream")
def translate_stream(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    source_lang = detect_language(payload.text)

    try:
        generator = translate_text(
            text=payload.text,
            target_lang=payload.target_lang,
            stream=True,
        )
    except AppError as exc:
        raise map_app_error(exc) from exc

    return StreamingResponse(
        _safe_stream(generator),
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Source-Lang": source_lang,
            "X-Target-Lang": payload.target_lang,
        },
    )