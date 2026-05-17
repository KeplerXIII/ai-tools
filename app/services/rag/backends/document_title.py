"""Заголовок документа для RAG/UI: перевод, иначе оригинал."""

from __future__ import annotations

from sqlalchemy import func

from app.infrastructure.db.models import Document


def document_display_title_column():
    """SQL-выражение: coalesce(trim(translated_title), title)."""
    return func.coalesce(
        func.nullif(func.trim(Document.translated_title), ""),
        Document.title,
    ).label("title")
