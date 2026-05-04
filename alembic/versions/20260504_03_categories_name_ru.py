"""categories.name_ru for bilingual taxonomy labels

Revision ID: 20260504_03
Revises: 20260504_02
Create Date: 2026-05-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260504_03"
down_revision: str | None = "20260504_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("name_ru", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("categories", "name_ru")
