"""parse runs: phase + processing_job; processing_jobs document_id nullable + source_id

Revision ID: 20260512_02
Revises: 20260512_01
Create Date: 2026-05-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260512_02"
down_revision: str | None = "20260512_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "processing_jobs",
        "document_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.add_column(
        "processing_jobs",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_processing_jobs_source_id_sources"),
        "processing_jobs",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_processing_jobs_source_id"),
        "processing_jobs",
        ["source_id"],
        unique=False,
    )

    op.add_column(
        "source_parse_runs",
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "source_parse_runs",
        sa.Column("phase", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_source_parse_runs_processing_job_id_processing_jobs"),
        "source_parse_runs",
        "processing_jobs",
        ["processing_job_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_source_parse_runs_processing_job_id"),
        "source_parse_runs",
        ["processing_job_id"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError("Откат не поддерживается.")
