"""categories.description_ru for Russian taxonomy blurbs

Revision ID: 20260504_04
Revises: 20260504_03
Create Date: 2026-05-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260504_04"
down_revision: str | None = "20260504_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column("description_ru", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("categories", "description_ru")
