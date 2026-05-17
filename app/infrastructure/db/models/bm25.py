from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class DocumentChunkTerm(Base):
    """Инвертированный индекс термов чанка (BM25 Okapi)."""

    __tablename__ = "document_chunk_terms"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_chunks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    term: Mapped[str] = mapped_column(String(128), primary_key=True)
    tf: Mapped[int] = mapped_column(Integer, nullable=False)
