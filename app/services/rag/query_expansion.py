"""Расширение запроса (multi-query) через LLM — опционально."""

from __future__ import annotations

from app.bootstrap.container import get_llm_client
from app.core.config import settings
from app.core.llm_task import LLMTask
from app.ports.llm import LLMRequest


def _parse_alternatives(raw: str, *, original: str) -> list[str]:
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    out: list[str] = [original]
    for line in lines:
        cleaned = line.lstrip("0123456789.-) ").strip()
        if cleaned and cleaned.lower() != original.lower() and cleaned not in out:
            out.append(cleaned)
        if len(out) >= settings.rag_query_expansion_count + 1:
            break
    return out


async def expand_search_queries(query: str) -> list[str]:
    """Возвращает [оригинал, …альтернативы] для multi-query + RRF."""
    q = query.strip()
    if not q:
        return []
    if not settings.rag_query_expansion:
        return [q]

    prompt = f"""
Сгенерируй {settings.rag_query_expansion_count} кратких поисковых запроса (по одной строке каждый)
для поиска по базе документов на ту же тему, что и запрос пользователя.
Не повторяй исходный запрос дословно. Только строки запросов, без нумерации и пояснений.

Запрос пользователя:
{q}
""".strip()

    llm = get_llm_client(LLMTask.RAG)
    raw = await llm.chat(
        LLMRequest(
            prompt=prompt,
            model=settings.model_rag,
            temperature=0.3,
            stream=False,
            max_tokens=256,
            meta={"tool": "rag_query_expansion"},
        ),
    )
    if not isinstance(raw, str) or not raw.strip():
        return [q]
    return _parse_alternatives(raw, original=q)
