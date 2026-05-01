import json
import re

from app.bootstrap.container import get_llm_client
from app.core.config import settings
from app.domain.errors import InvalidProviderResponseError, ValidationError
from app.ports.llm import LLMRequest


def extract_json_object(content: str) -> dict:
    content = content.strip()

    content = (
        content
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )

    match = re.search(r"\{.*\}", content, re.DOTALL)

    if not match:
        raise InvalidProviderResponseError(f"LLM не вернула JSON: {content[:500]}")

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise InvalidProviderResponseError(
            f"LLM вернула невалидный JSON: {exc}. Ответ: {content[:500]}"
        ) from exc


def normalize_list(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        return [value.strip()] if value.strip() else []

    if not isinstance(value, list):
        value = [value]

    result: list[str] = []

    for item in value:
        if item is None:
            continue

        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = "; ".join(
                f"{key}: {val}"
                for key, val in item.items()
                if val is not None and str(val).strip()
            )
        else:
            text = str(item).strip()

        if text:
            result.append(text)

    return result


def extract_entities(text: str) -> dict:
    if not text.strip():
        raise ValidationError("Текст пустой")

    prompt = f"""
Извлеки из текста следующие сущности:

1. Упоминания образцов вооружения и военной техники.
2. Производителей, разработчиков, оборонные компании.
3. Контракты, сделки, закупки, поставки, суммы, сроки, заказчиков.

Верни только валидный JSON без markdown, без пояснений, без текста до и после JSON.

Все элементы массивов должны быть строками, не объектами.

Формат ответа:

{{
  "military_equipment": [],
  "manufacturers": [],
  "contracts": []
}}

Текст:
{text}
"""

    llm = get_llm_client()
    content = llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_entity_extraction,
            temperature=0,
        )
    )

    data = extract_json_object(content)

    return {
        "military_equipment": normalize_list(data.get("military_equipment")),
        "manufacturers": normalize_list(data.get("manufacturers")),
        "contracts": normalize_list(data.get("contracts")),
    }