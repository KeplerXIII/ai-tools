"""source_parse_runs.post_parse_options (LLM после разбора).

Revision ID: 20260512_03
Revises: 20260512_02
Create Date: 2026-05-12

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260512_03"
down_revision: str | None = "20260512_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_parse_runs",
        sa.Column("post_parse_options", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_parse_runs", "post_parse_options")
