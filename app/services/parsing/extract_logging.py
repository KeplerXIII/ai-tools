"""Структурированные логи парсера (имя логгера `extract`, формат как у `llm`)."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger("extract")


def url_preview(raw: str | None, max_len: int = 96) -> str | None:
    """Короткая форма URL для логов (без обрезки хоста)."""
    if not raw:
        return None
    s = raw.strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def url_host(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return urlparse(raw).netloc or None
    except ValueError:
        return None
