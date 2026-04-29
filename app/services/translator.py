from typing import Generator

from langdetect import detect

from app.core.config import settings
from app.services.llm_openrouter_client import chat


LANG_MAP = {
    "en": ("English", "en"),
    "de": ("German", "de"),
    "ar": ("Arabic", "ar"),
    "zh": ("Chinese", "zh"),
    "ru": ("Russian", "ru"),
}


def build_prompt(text: str, source: str, target: str) -> str:
    src_name, src_code = LANG_MAP[source]
    tgt_name, tgt_code = LANG_MAP[target]

    return f"""You are a professional {src_name} ({src_code}) to {tgt_name} ({tgt_code}) translator. Your goal is to accurately convey the meaning and nuances of the original {src_name} text while adhering to {tgt_name} grammar, vocabulary, and cultural sensitivities.
Produce only the {tgt_name} translation, without any additional explanations or commentary. Please translate the following {src_name} text into {tgt_name}:

{text}
"""


def detect_language(text: str) -> str:
    try:
        lang = detect(text)
    except Exception:
        return "en"

    return lang if lang in LANG_MAP else "en"


def translate_text(
    text: str,
    target_lang: str = "ru",
    stream: bool = False,
) -> str | Generator[str, None, None]:
    source_lang = detect_language(text)
    prompt = build_prompt(
        text=text,
        source=source_lang,
        target=target_lang,
    )

    return chat(
        prompt=prompt,
        model=settings.openrouter_model,
        temperature=0,
        stream=stream,
        meta={
            "tool": "translator",
            "source_lang": source_lang,
            "target_lang": target_lang,
            "text_chars": len(text),
        },
    )