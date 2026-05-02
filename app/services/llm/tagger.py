import json
import re

from app.bootstrap.container import get_llm_client
from app.core.config import settings
from app.core.llm_task import LLMTask
from app.domain.errors import InvalidProviderResponseError, ValidationError
from app.ports.llm import LLMRequest


def extract_json_object(raw: str) -> dict:
    """
    Достаёт JSON даже если модель обернула его в ```json ... ```
    или добавила лишний текст.
    """
    raw = raw.strip()

    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise InvalidProviderResponseError(f"LLM не вернула JSON: {raw[:500]}")

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise InvalidProviderResponseError(f"Некорректный JSON от LLM: {exc}") from exc


def tag_text(text: str, max_tags: int = 12) -> dict:
    if not text or not text.strip():
        raise ValidationError("Текст пустой")

    prompt = f"""
Ты выполняешь тематическое тегирование текста.

Верни только JSON без markdown, без пояснений, без текста вокруг.

Формат ответа:
{{
  "tags": ["tag 1", "tag 2", "tag 3"]
}}

Правила:
- используй только содержание текста
- не добавляй внешние знания
- теги короткие: 1-4 слова
- язык тегов: тот же, что и язык исходного текста
- если текст на немецком — теги на немецком
- если текст на английском — теги на английском
- если текст на русском — теги на русском
- не более {max_tags} тегов
- без повторов

Текст:
{text}
""".strip()

    llm = get_llm_client(LLMTask.TAGGING)
    raw = llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_tagging,
            temperature=0,
            meta={"op": "tagging"},
        )
    )

    data = extract_json_object(raw)

    tags = data.get("tags", [])

    if not isinstance(tags, list):
        return {"tags": []}

    clean = []

    for tag in tags:
        tag = str(tag).strip()

        if not tag:
            continue

        if tag not in clean:
            clean.append(tag)

    return {
        "tags": clean[:max_tags],
    }
