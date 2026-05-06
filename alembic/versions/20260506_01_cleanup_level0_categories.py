"""delete legacy level-0 categories and assignments

Revision ID: 20260506_01
Revises: 20260505_03
Create Date: 2026-05-06

"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260506_01"
down_revision: str | None = "20260505_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM document_categories dc
        USING categories c
        WHERE dc.category_id = c.id
          AND c.level = 0
        """
    )
    op.execute("DELETE FROM categories WHERE level = 0")


def downgrade() -> None:
    # Legacy level-0 categories are intentionally removed and not restored.
    pass
