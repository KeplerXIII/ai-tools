from fastapi import HTTPException

from app.core.config import settings
from app.services.llm_ollama_client import chat_structured


TAG_SCHEMA = {
    "type": "object",
    "properties": {
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["tags"],
}


def tag_text(text: str, max_tags: int = 12) -> dict:
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Текст пустой",
        )

    prompt = f"""
Ты выполняешь тематическое тегирование текста.

Правила:
- используй только содержание текста
- не добавляй внешние знания
- теги короткие (1-4 слова)
- на русском языке
- не более {max_tags} тегов
- верни строго JSON

Текст:
{text}
"""

    data = chat_structured(
        prompt=prompt,
        schema=TAG_SCHEMA,
        model=settings.llm_model,
        temperature=0,
    )

    tags = data.get("tags", [])

    if not isinstance(tags, list):
        return {"tags": []}

    # нормализация
    clean = []
    for t in tags:
        tag = str(t).strip()
        if tag and tag not in clean:
            clean.append(tag)

    return {
        "tags": clean[:max_tags],
    }