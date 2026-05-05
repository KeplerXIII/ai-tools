"""document extract metadata (author, date, method, quality)

Revision ID: 20260505_03
Revises: 20260505_02
Create Date: 2026-05-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260505_03"
down_revision: str | None = "20260505_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("extracted_author", sa.String(length=512), nullable=True))
    op.add_column("documents", sa.Column("extracted_date", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("extract_method", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("extract_quality", sa.String(length=32), nullable=True))
    op.add_column(
        "documents",
        sa.Column("extract_needs_review", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "extract_needs_review")
    op.drop_column("documents", "extract_quality")
    op.drop_column("documents", "extract_method")
    op.drop_column("documents", "extracted_date")
    op.drop_column("documents", "extracted_author")
