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
