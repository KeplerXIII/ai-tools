"""workbooks и workbook_documents (M2M к documents).

Revision ID: 20260522_01
Revises: 20260521_01
Create Date: 2026-05-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260522_01"
down_revision: str | None = "20260521_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workbooks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("generation_prompt", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workbooks_user_id", "workbooks", ["user_id"])

    op.create_table(
        "workbook_documents",
        sa.Column(
            "workbook_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workbooks.id", ondelete="CASCADE"),
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
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workbook_documents_document_id", "workbook_documents", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_workbook_documents_document_id", table_name="workbook_documents")
    op.drop_table("workbook_documents")
    op.drop_index("ix_workbooks_user_id", table_name="workbooks")
    op.drop_table("workbooks")
