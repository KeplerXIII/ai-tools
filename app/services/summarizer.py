from fastapi import HTTPException

from app.core.config import settings
from app.services.llm_client import chat


def summarize_text(text: str) -> str:
    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="Текст пустой",
        )

    prompt = f"""
Составь краткую аналитическую аннотацию на русском языке.

Требования:
- 5–7 предложений;
- без воды;
- отразить суть события;
- указать участников, технику, контракты или поставки, если они есть;
- не добавлять фактов, которых нет в тексте.

Текст:
{text}
"""

    return chat(
        prompt=prompt,
        model=settings.llm_model,
        temperature=0.2,
    )