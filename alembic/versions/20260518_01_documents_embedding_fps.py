"""documents: отпечатки источника для актуальности эмбеддингов.

Revision ID: 20260518_01
Revises: 20260517_01
Create Date: 2026-05-18

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260518_01"
down_revision: str | None = "20260517_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    op.add_column(
        "documents",
        sa.Column("embedding_original_fp", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("embedding_translated_fp", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("embedding_annotation_fp", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "embedding_annotation_fp")
    op.drop_column("documents", "embedding_translated_fp")
    op.drop_column("documents", "embedding_original_fp")
