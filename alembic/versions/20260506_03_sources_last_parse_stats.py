"""sources: last parse timestamp and created count

Revision ID: 20260506_03
Revises: 20260506_02
Create Date: 2026-05-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260506_03"
down_revision: str | None = "20260506_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("last_parse_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sources",
        sa.Column("last_parse_created_total", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sources", "last_parse_created_total")
    op.drop_column("sources", "last_parse_at")
