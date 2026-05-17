"""document_chunks: GIN full-text index (russian) для hybrid RAG.

Revision ID: 20260520_01
Revises: 20260519_01
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_01"
down_revision: str | None = "20260519_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FTS_INDEX = "ix_document_chunks_content_fts_ru"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE INDEX IF NOT EXISTS {FTS_INDEX}
            ON document_chunks
            USING gin (to_tsvector('russian', coalesce(content, '')))
            """,
        ),
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {FTS_INDEX}"))
