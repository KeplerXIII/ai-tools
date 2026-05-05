"""add extracted images fields to documents

Revision ID: 20260505_02
Revises: 20260505_01
Create Date: 2026-05-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260505_02"
down_revision: str | None = "20260505_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extracted_images", sa.JSON(), nullable=True))
    op.add_column("documents", sa.Column("extracted_main_image", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "extracted_main_image")
    op.drop_column("documents", "extracted_images")
