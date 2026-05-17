"""Промпт RAG: system + контекст с нумерованными источниками."""

from __future__ import annotations

from app.services.rag.types import RetrievedChunk


def build_rag_prompt(*, query: str, chunks: tuple[RetrievedChunk, ...]) -> str:
    context_blocks: list[str] = []
    for chunk in chunks:
        label = chunk.rank or len(context_blocks) + 1
        url_part = f", {chunk.source_url}" if chunk.source_url else ""
        context_blocks.append(
            f"--- Источник [{label}]: {chunk.title}{url_part} "
            f"(тип: {chunk.chunk_type}, фрагмент #{chunk.chunk_index}) ---\n"
            f"{chunk.content.strip()}",
        )

    context = "\n\n".join(context_blocks) if context_blocks else "(контекст пуст)"

    return f"""
Ты отвечаешь на вопрос пользователя строго по приведённому контексту из базы документов.

Правила:
- используй только факты из блоков «Источник [N]»;
- если в контексте нет ответа — прямо скажи, что данных недостаточно;
- не выдумывай факты и не опирайся на внешние знания;
- при ссылке на факт указывай номер источника в квадратных скобках, например [1];
- отвечай на русском языке, ясно и по существу.

Контекст:
{context}

Вопрос пользователя:
{query.strip()}
""".strip()
