"""workbooks.notes и источники записей (workbook_entry_documents).

Revision ID: 20260523_01
Revises: 20260522_02
Create Date: 2026-05-23
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260523_01"
down_revision: str | None = "20260522_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workbooks", sa.Column("notes", sa.Text(), nullable=True))

    op.create_table(
        "workbook_entry_documents",
        sa.Column(
            "entry_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workbook_entries.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workbook_entry_documents_document_id", "workbook_entry_documents", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_workbook_entry_documents_document_id", table_name="workbook_entry_documents")
    op.drop_table("workbook_entry_documents")
    op.drop_column("workbooks", "notes")
