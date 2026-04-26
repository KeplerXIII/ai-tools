# app/api/v1/endpoints/translate.py

from fastapi import APIRouter
import requests

from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.translator import detect_language, build_prompt

router = APIRouter(prefix="/translate", tags=["translate"])


@router.post("", response_model=TranslateResponse)
def translate(payload: TranslateRequest):
    source_lang = detect_language(payload.text)
    target_lang = payload.target_lang

    prompt = build_prompt(payload.text, source_lang, target_lang)

    # твой vLLM / Ollama / OpenAI endpoint
    response = requests.post(
        "http://172.20.0.1:11434/v1/chat/completions",  # пример (ollama)
        json={
            "model": "translategemma:12b",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0
        },
        timeout=60
    )

    result = response.json()

    translation = result["choices"][0]["message"]["content"].strip()

    return {
        "source_lang": source_lang,
        "target_lang": target_lang,
        "translation": translation,
    }