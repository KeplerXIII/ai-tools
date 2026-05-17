"""rag_queries: лог запросов RAG (фаза 4).

Revision ID: 20260520_02
Revises: 20260520_01
Create Date: 2026-05-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260520_02"
down_revision: str | None = "20260520_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_queries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expanded_queries", sa.JSON(), nullable=True),
        sa.Column("retrieval_strategy", sa.String(length=32), nullable=False),
        sa.Column("reranker", sa.String(length=32), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("chunk_ids", sa.JSON(), nullable=True),
        sa.Column("retrieve_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("retrieval_ms", sa.Integer(), nullable=True),
        sa.Column("generation_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(op.f("ix_rag_queries_user_id"), "rag_queries", ["user_id"], unique=False)
    op.create_index(op.f("ix_rag_queries_created_at"), "rag_queries", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rag_queries_created_at"), table_name="rag_queries")
    op.drop_index(op.f("ix_rag_queries_user_id"), table_name="rag_queries")
    op.drop_table("rag_queries")
