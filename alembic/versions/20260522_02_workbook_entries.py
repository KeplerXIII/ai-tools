"""workbook_entries: записи (тезисы) в рабочей тетради.

Revision ID: 20260522_02
Revises: 20260522_01
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_02"
down_revision: str | None = "20260522_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workbook_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "workbook_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workbook_entries_workbook_id", "workbook_entries", ["workbook_id"])


def downgrade() -> None:
    op.drop_index("ix_workbook_entries_workbook_id", table_name="workbook_entries")
    op.drop_table("workbook_entries")
