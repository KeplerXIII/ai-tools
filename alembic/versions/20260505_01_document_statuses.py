"""document statuses and assignments

Revision ID: 20260505_01
Revises: 20260504_04
Create Date: 2026-05-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260505_01"
down_revision: str | None = "20260504_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_statuses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name_ru", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "document_status_assignments",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["status_id"], ["document_statuses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "status_id"),
    )


def downgrade() -> None:
    op.drop_table("document_status_assignments")
    op.drop_table("document_statuses")
