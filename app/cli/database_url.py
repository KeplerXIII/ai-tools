"""URL БД для CLI (миграции и сиды): учитывает ``DATABASE_URL_FOR_CLI``."""

from __future__ import annotations

import os

from app.core.config import settings


def async_database_url_for_cli() -> str:
    return os.environ.get("DATABASE_URL_FOR_CLI", "").strip() or settings.database_url
