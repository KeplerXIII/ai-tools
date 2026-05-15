"""sources.rss_urls

Revision ID: 20260516_01
Revises: 20260515_01
Create Date: 2026-05-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_01"
down_revision: str | None = "20260515_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("rss_urls", sa.JSON(), nullable=True))
    op.execute(
        """
        UPDATE sources
        SET rss_urls = json_build_array(rss_url)
        WHERE rss_url IS NOT NULL AND rss_url <> ''
        """,
    )


def downgrade() -> None:
    op.drop_column("sources", "rss_urls")
