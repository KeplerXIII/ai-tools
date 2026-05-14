"""documents.translated_title

Revision ID: 20260514_01
Revises: 20260512_03
Create Date: 2026-05-14

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260514_01"
down_revision: str | None = "20260512_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("translated_title", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "translated_title")
