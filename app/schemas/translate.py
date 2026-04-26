from pydantic import BaseModel


class TranslateRequest(BaseModel):
    text: str
    target_lang: str = "ru"  # по умолчанию русский


class TranslateResponse(BaseModel):
    source_lang: str
    target_lang: str
    translation: str