"""Утилиты для SSE/LLM-стримов: не блокировать остальные запросы к тому же процессу."""

import asyncio
from collections.abc import AsyncIterator


async def bytes_from_text_stream(stream: AsyncIterator[str]) -> AsyncIterator[bytes]:
    """
    Кодирует текстовые чанки в UTF-8 и отдаёт квант event loop после каждого чанка,
    чтобы параллельно обрабатывались /docs, /admin и другие короткие запросы.
    """
    async for chunk in stream:
        s = chunk if isinstance(chunk, str) else str(chunk)
        yield s.encode("utf-8")
        await asyncio.sleep(0)


def sse_data_event_bytes(payload: str) -> bytes:
    """Один SSE-фрейм в формате ``data:`` (как в documents translate/summary stream)."""
    lines = payload.splitlines() or [""]
    body = "".join(f"data: {line}\n" for line in lines)
    return f"{body}\n".encode("utf-8")


def sse_error_event_bytes(message: str) -> bytes:
    safe = message.replace("\n", " ").strip()
    return f"event: error\ndata: {safe}\n\n".encode("utf-8")


async def coop_text_chunks(stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Текстовый стрим с yield точками между чанками (как bytes_from_text_stream, без кодирования)."""
    async for chunk in stream:
        s = chunk if isinstance(chunk, str) else str(chunk)
        yield s
        await asyncio.sleep(0)
