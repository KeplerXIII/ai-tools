"""document_types.description for catalog comments

Revision ID: 20260504_02
Revises: 20260504_01
Create Date: 2026-05-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260504_02"
down_revision: str | None = "20260504_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_types",
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_types", "description")
