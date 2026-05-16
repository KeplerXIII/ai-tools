"""document_embeddings: vector dimension 1024 for bge-m3 (backend-agnostic).

Revision ID: 20260517_01
Revises: 20260516_01
Create Date: 2026-05-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_01"
down_revision: str | None = "20260516_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Как в первоначальной миграции домена documents (20260504_01_documents_domain_pgvector).
OLD_DIM = 1536
NEW_DIM = 1024


def upgrade() -> None:
    op.execute(
        sa.text(f"ALTER TABLE document_embeddings ALTER COLUMN embedding TYPE vector({NEW_DIM})"),
    )


def downgrade() -> None:
    # Нельзя сузить тип vector(N), пока в столбце есть векторы другой размерности.
    op.execute(sa.text("DELETE FROM document_embeddings"))
    op.execute(
        sa.text(f"ALTER TABLE document_embeddings ALTER COLUMN embedding TYPE vector({OLD_DIM})"),
    )
