"""processing_jobs queue metadata

Revision ID: 20260508_01
Revises: 20260506_03
Create Date: 2026-05-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260508_01"
down_revision: str | None = "20260506_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.add_column("processing_jobs", sa.Column("queue_name", sa.String(length=64), nullable=True))
    op.add_column("processing_jobs", sa.Column("queue_job_key", sa.String(length=255), nullable=True))

    op.create_index(
        op.f("ix_processing_jobs_batch_id"),
        "processing_jobs",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_processing_jobs_queue_name"),
        "processing_jobs",
        ["queue_name"],
        unique=False,
    )
    op.create_index(
        op.f("ix_processing_jobs_queue_job_key"),
        "processing_jobs",
        ["queue_job_key"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError("Откат не поддерживается.")
