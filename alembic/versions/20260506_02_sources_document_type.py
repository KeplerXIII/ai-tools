"""sources.document_type_id FK to document_types

Revision ID: 20260506_02
Revises: 20260506_01
Create Date: 2026-05-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260506_02"
down_revision: str | None = "20260506_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("document_type_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_sources_document_type_id",
        "sources",
        "document_types",
        ["document_type_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE sources
        SET document_type_id = (SELECT id FROM document_types WHERE code = 'news' LIMIT 1)
        WHERE document_type_id IS NULL
        """
    )
    op.alter_column("sources", "document_type_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_sources_document_type_id", "sources", type_="foreignkey")
    op.drop_column("sources", "document_type_id")
