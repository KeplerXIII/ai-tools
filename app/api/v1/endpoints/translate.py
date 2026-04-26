from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.llm_client import chat
from app.services.translator import detect_language, build_prompt

router = APIRouter(prefix="/translate", tags=["translate"])


@router.post("", response_model=TranslateResponse)
def translate(payload: TranslateRequest):
    if not payload.text.strip():
        raise HTTPException(
            status_code=400,
            detail="Текст пустой",
        )

    source_lang = detect_language(payload.text)
    target_lang = payload.target_lang

    prompt = build_prompt(payload.text, source_lang, target_lang)

    translation = chat(
        prompt=prompt,
        model=settings.translate_model,
        temperature=0,
    )

    return TranslateResponse(
        source_lang=source_lang,
        target_lang=target_lang,
        translation=translation,
    )