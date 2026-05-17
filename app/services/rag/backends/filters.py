"""Общие metadata-фильтры для vector и lexical backends."""

from __future__ import annotations

from sqlalchemy import exists, select

from app.infrastructure.db.models import (
    Document,
    DocumentCategory,
    DocumentEntity,
    DocumentTag,
)
from app.services.rag.types import RetrievalFilters


def apply_document_metadata_filters(stmt, filters: RetrievalFilters):  # noqa: ANN001
    if filters.fund_id is not None:
        stmt = stmt.where(Document.fund_id == filters.fund_id)
    if filters.environment_id is not None:
        stmt = stmt.where(Document.environment_id == filters.environment_id)
    if filters.source_id is not None:
        stmt = stmt.where(Document.source_id == filters.source_id)
    if filters.published_from is not None:
        stmt = stmt.where(Document.published_at >= filters.published_from)
    if filters.published_to is not None:
        stmt = stmt.where(Document.published_at <= filters.published_to)
    if filters.tag_ids:
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(DocumentTag)
                .where(
                    DocumentTag.document_id == Document.id,
                    DocumentTag.tag_id.in_(filters.tag_ids),
                ),
            ),
        )
    if filters.category_ids:
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(DocumentCategory)
                .where(
                    DocumentCategory.document_id == Document.id,
                    DocumentCategory.category_id.in_(filters.category_ids),
                ),
            ),
        )
    if filters.entity_ids:
        stmt = stmt.where(
            exists(
                select(1)
                .select_from(DocumentEntity)
                .where(
                    DocumentEntity.document_id == Document.id,
                    DocumentEntity.entity_id.in_(filters.entity_ids),
                ),
            ),
        )
    return stmt
