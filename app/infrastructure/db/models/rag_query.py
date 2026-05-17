from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base


class RagQuery(Base):
    __tablename__ = "rag_queries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expanded_queries: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    retrieval_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    reranker: Mapped[str] = mapped_column(String(32), nullable=False)
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    chunk_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    retrieve_only: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    retrieval_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generation_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
