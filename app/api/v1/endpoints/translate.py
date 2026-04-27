from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.translator import detect_language, translate_text

router = APIRouter(prefix="/translate", tags=["translate"])


@router.post("", response_model=TranslateResponse)
def translate(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    source_lang = detect_language(payload.text)

    translation = translate_text(
        text=payload.text,
        target_lang=payload.target_lang,
        stream=False,
    )

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

    generator = translate_text(
        text=payload.text,
        target_lang=payload.target_lang,
        stream=True,
    )

    return StreamingResponse(
        generator,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Source-Lang": source_lang,
            "X-Target-Lang": payload.target_lang,
        },
    )