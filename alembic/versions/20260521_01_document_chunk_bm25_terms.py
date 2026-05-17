"""document_chunk_terms: inverted index для BM25 (Okapi).

Revision ID: 20260521_01
Revises: 20260520_02
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260521_01"
down_revision: str | None = "20260520_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_chunk_terms",
        sa.Column(
            "chunk_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("document_chunks.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("term", sa.String(length=128), primary_key=True, nullable=False),
        sa.Column("tf", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_document_chunk_terms_term",
        "document_chunk_terms",
        ["term"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunk_terms_term", table_name="document_chunk_terms")
    op.drop_table("document_chunk_terms")
