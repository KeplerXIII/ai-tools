from typing import Generator

from fastapi import HTTPException

from app.core.config import settings
from app.schemas.extract import RefineSummaryMode
from app.services.llm_openaisdk_client import chat


def build_summary_prompt(text: str) -> str:
    return f"""
Ты выполняешь аннотирование статьи строго по предоставленному тексту.

Правила:
- используй только факты из текста ниже;
- не используй внешние знания;
- не добавляй предположения, выводы и уточнения, которых нет в тексте;
- если в тексте не указаны сумма, сроки, заказчик, страна, количество или характеристики — не упоминай их;
- не расшифровывай и не описывай технику сверх того, что сказано в тексте;
- составь аннотацию на русском языке;
- объём: 4–7 предложений;
- стиль: сухой аналитический.

Проверь каждое предложение аннотации: оно должно опираться на конкретную информацию из текста.
Если информации недостаточно, напиши кратко и без домыслов.

Текст:
{text}
""".strip()


def summarize_text(
    text: str,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    if not text.strip():
        raise HTTPException(status_code=400, detail="Текст пустой")

    prompt = build_summary_prompt(text)

    return chat(
        prompt=prompt,
        model=settings.llm_model,
        temperature=0.2,
        stream=stream,
        meta={
            "tool": "summarizer",
            "text_chars": len(text),
        },
    )


def build_refine_summary_prompt(
    article_text: str,
    summary: str,
    user_instruction: str,
    mode: RefineSummaryMode,
) -> str:
    mode_instructions = {
        RefineSummaryMode.shorten: (
            "Сократи аннотацию, сохранив ключевые факты и цифры. Убери повторы и лишнее."
        ),
        RefineSummaryMode.expand: (
            "Расширь аннотацию, добавляя детали из исходного текста."
        ),
        RefineSummaryMode.add_context: (
            "Улучши аннотацию с учётом указаний пользователя. "
            "Можно добавить внешний контекст, но без выдуманных фактов."
        ),
    }

    instruction = user_instruction.strip() or "Нет дополнительных указаний."

    return f"""
Ты — аналитик, который улучшает аннотации.

Источники:
1. Исходный текст — главный источник фактов
2. Аннотация — черновик
3. Указание пользователя — доп. контекст

Исходный текст:
{article_text}

Аннотация:
{summary}

Указание:
{instruction}

Режим:
{mode.value}

Инструкция:
{mode_instructions[mode]}

Правила:
- русский язык
- не выдумывать факты
- не терять цифры, названия, программы
- можно аккуратно добавить внешний контекст
- вернуть только финальную аннотацию

Результат:
""".strip()


def refine_summary(
    article_text: str,
    summary: str,
    user_instruction: str,
    mode: RefineSummaryMode,
    stream: bool = False,
) -> str | Generator[str, None, None]:

    if not article_text.strip():
        raise HTTPException(status_code=400, detail="Исходный текст пустой")

    if not summary.strip():
        raise HTTPException(status_code=400, detail="Аннотация пустая")

    prompt = build_refine_summary_prompt(
        article_text=article_text,
        summary=summary,
        user_instruction=user_instruction,
        mode=mode,
    )

    return chat(
        prompt=prompt,
        model=settings.llm_model,
        temperature=0.2,
        stream=stream,
        meta={
            "tool": "summary_refiner",
            "mode": mode.value,
        },
    )