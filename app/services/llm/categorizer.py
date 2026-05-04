from app.bootstrap.container import get_llm_client
from app.core.config import settings
from app.core.llm_task import LLMTask
from app.domain.errors import ValidationError
from app.ports.llm import LLMRequest
from app.services.llm.tagger import extract_json_object


async def categorize_text(text: str, categories: list[tuple[str, str]]) -> list[dict]:
    """
    categories: список (code, name) активных категорий из БД.
    Возвращает [{"code": str, "confidence": float}, ...] (только известные code).
    """
    if not text or not text.strip():
        raise ValidationError("Текст пустой")
    if not categories:
        return []

    known_codes = {c[0] for c in categories}
    lines = "\n".join(f"- {code}: {name}" for code, name in categories)

    prompt = f"""
Ты выполняешь категоризацию текста по заданному списку категорий.

Верни только JSON без markdown и без текста вокруг.

Формат:
{{
  "categories": [
    {{"code": "код_из_списка", "confidence": 0.0 до 1.0}}
  ]
}}

Правила:
- выбирай только коды из списка ниже;
- не более 5 категорий;
- confidence отражает уверенность в релевантности текста категории;
- если ни одна категория не подходит, верни пустой массив categories.

Допустимые категории:
{lines}

Текст:
{text}
""".strip()

    llm = get_llm_client(LLMTask.CATEGORIZATION)
    raw = await llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_categorization,
            temperature=0,
            meta={"op": "categorization"},
        )
    )
    if not isinstance(raw, str):
        return []

    data = extract_json_object(raw)
    raw_items = data.get("categories", [])
    if not isinstance(raw_items, list):
        return []

    out: list[dict] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code", "")).strip()
        if code not in known_codes:
            continue
        conf = item.get("confidence", 0.5)
        try:
            conf_f = float(conf)
        except (TypeError, ValueError):
            conf_f = 0.5
        conf_f = max(0.0, min(1.0, conf_f))
        out.append({"code": code, "confidence": conf_f})

    return out[:5]
