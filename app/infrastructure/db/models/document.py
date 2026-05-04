from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.base import Base

# Должен совпадать с dimension основной модели в embedding_models (сиды / миграция).
EMBEDDING_VECTOR_DIM = 1536


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_content: Mapped[str] = mapped_column(Text, nullable=False)
    original_language_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("languages.id"), nullable=False)
    original_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    translated_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    translated_language_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("languages.id"),
        nullable=True,
    )
    translated_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    document_type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_types.id"), nullable=False)
    environment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("environments.id"), nullable=True)
    fund_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("funds.id"), nullable=True)

    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    locked_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    original_summary_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    translated_summary_stale: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")


class DocumentCategory(Base):
    __tablename__ = "document_categories"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    prediction_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prediction_sources.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    prediction_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prediction_sources.id"),
        nullable=True,
    )


class DocumentEntity(Base):
    __tablename__ = "document_entities"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"),
        primary_key=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    prediction_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("prediction_sources.id"),
        nullable=True,
    )
    source_fragment: Mapped[str | None] = mapped_column(Text, nullable=True)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    language_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("languages.id"), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(32), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "language_id",
            "chunk_type",
            "chunk_index",
            name="uq_document_chunks_doc_lang_type_idx",
        ),
    )


class DocumentEmbedding(Base):
    __tablename__ = "document_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False)
    embedding_model_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("embedding_models.id"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_VECTOR_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_model_id", name="uq_document_embeddings_chunk_model"),
    )


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)

    started_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
