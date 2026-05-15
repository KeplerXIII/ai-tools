"""sources.discovery_paths

Revision ID: 20260515_01
Revises: 20260514_01
Create Date: 2026-05-15

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260515_01"
down_revision: str | None = "20260514_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("discovery_paths", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "discovery_paths")
