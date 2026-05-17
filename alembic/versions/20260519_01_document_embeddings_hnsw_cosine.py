"""document_embeddings: HNSW index (cosine) for RAG retrieval.

Revision ID: 20260519_01
Revises: 20260518_01
Create Date: 2026-05-19

Параметры индекса (pgvector, 1024-dim bge-m3):
- vector_cosine_ops + оператор <=> в запросах (см. app/services/rag/backends/vector.py).
- m=16: баланс recall/размер для типичного корпуса до ~500k чанков; при росте >1M
  рассмотреть m=24 в новой миграции (пересоздание индекса).
- ef_construction=128: качество графа при построении (дефолт pgvector 64; 128 — выше recall
  при INSERT/REINDEX, дольше первая сборка).
- ef_search задаётся в runtime (settings.rag_hnsw_ef_search), не в индексе.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260519_01"
down_revision: str | None = "20260518_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Зафиксированы в миграции; дублируются в config для документации / тестов.
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 128

INDEX_NAME = "ix_document_embeddings_embedding_hnsw_cosine"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE INDEX IF NOT EXISTS {INDEX_NAME}
            ON document_embeddings
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION})
            """,
        ),
    )


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {INDEX_NAME}"))
