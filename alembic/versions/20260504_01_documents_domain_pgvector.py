"""documents domain, pgvector

Revision ID: 20260504_01
Revises: 20260205_01
Create Date: 2026-05-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy import inspect

revision: str = "20260504_01"
down_revision: str | None = "20260205_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 1536


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "documents" in inspector.get_table_names():
        return

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_roles_code"), "roles", ["code"], unique=True)
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.Uuid(as_uuid=True), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "languages",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
    )
    op.create_index(op.f("ix_languages_code"), "languages", ["code"], unique=True)
    op.create_index(op.f("ix_languages_name"), "languages", ["name"], unique=True)

    op.create_table(
        "countries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
    )
    op.create_index(op.f("ix_countries_code"), "countries", ["code"], unique=True)
    op.create_index(op.f("ix_countries_name"), "countries", ["name"], unique=True)

    op.create_table(
        "prediction_sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_prediction_sources_code"), "prediction_sources", ["code"], unique=True)
    op.create_index(op.f("ix_prediction_sources_name"), "prediction_sources", ["name"], unique=True)

    op.create_table(
        "document_types",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
    )
    op.create_index(op.f("ix_document_types_code"), "document_types", ["code"], unique=True)
    op.create_index(op.f("ix_document_types_name"), "document_types", ["name"], unique=True)

    op.create_table(
        "environments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_environments_code"), "environments", ["code"], unique=True)
    op.create_index(op.f("ix_environments_name"), "environments", ["name"], unique=True)

    op.create_table(
        "funds",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_funds_code"), "funds", ["code"], unique=True)
    op.create_index(op.f("ix_funds_name"), "funds", ["name"], unique=True)

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("parent_id", sa.Uuid(as_uuid=True), sa.ForeignKey("categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_categories_code"), "categories", ["code"], unique=True)

    op.create_table(
        "entity_types",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index(op.f("ix_entity_types_code"), "entity_types", ["code"], unique=True)
    op.create_index(op.f("ix_entity_types_name"), "entity_types", ["name"], unique=True)

    op.create_table(
        "embedding_models",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_embedding_models_name"), "embedding_models", ["name"], unique=True)

    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("country_id", sa.Uuid(as_uuid=True), sa.ForeignKey("countries.id"), nullable=True),
        sa.Column("language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=False),
        sa.Column("rss_url", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "url", name="uq_sources_user_url"),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("original_content", sa.Text(), nullable=False),
        sa.Column("original_language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=False),
        sa.Column("original_summary", sa.Text(), nullable=True),
        sa.Column("translated_content", sa.Text(), nullable=True),
        sa.Column("translated_language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=True),
        sa.Column("translated_summary", sa.Text(), nullable=True),
        sa.Column("document_type_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_types.id"), nullable=False),
        sa.Column("environment_id", sa.Uuid(as_uuid=True), sa.ForeignKey("environments.id"), nullable=True),
        sa.Column("fund_id", sa.Uuid(as_uuid=True), sa.ForeignKey("funds.id"), nullable=True),
        sa.Column("source_id", sa.Uuid(as_uuid=True), sa.ForeignKey("sources.id"), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("locked_by_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("original_summary_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("translated_summary_stale", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(op.f("ix_documents_source_url"), "documents", ["source_url"], unique=False)
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_documents_source_url_not_null ON documents (source_url) "
            "WHERE source_url IS NOT NULL"
        )
    )

    op.create_table(
        "document_categories",
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("category_id", sa.Uuid(as_uuid=True), sa.ForeignKey("categories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("confidence", sa.Numeric(12, 6), nullable=True),
        sa.Column("prediction_source_id", sa.Uuid(as_uuid=True), sa.ForeignKey("prediction_sources.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=False),
        sa.UniqueConstraint("name", "language_id", name="uq_tags_name_language"),
    )

    op.create_table(
        "document_tags",
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Uuid(as_uuid=True), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("confidence", sa.Numeric(12, 6), nullable=True),
        sa.Column("prediction_source_id", sa.Uuid(as_uuid=True), sa.ForeignKey("prediction_sources.id"), nullable=True),
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("entity_type_id", sa.Uuid(as_uuid=True), sa.ForeignKey("entity_types.id"), nullable=False),
        sa.Column("language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("entity_type_id", "language_id", "name", name="uq_entities_type_lang_name"),
    )

    op.create_table(
        "document_entities",
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("confidence", sa.Numeric(12, 6), nullable=True),
        sa.Column("prediction_source_id", sa.Uuid(as_uuid=True), sa.ForeignKey("prediction_sources.id"), nullable=True),
        sa.Column("source_fragment", sa.Text(), nullable=True),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("language_id", sa.Uuid(as_uuid=True), sa.ForeignKey("languages.id"), nullable=False),
        sa.Column("chunk_type", sa.String(length=32), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "document_id",
            "language_id",
            "chunk_type",
            "chunk_index",
            name="uq_document_chunks_doc_lang_type_idx",
        ),
    )

    op.create_table(
        "document_embeddings",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("chunk_id", sa.Uuid(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("embedding_model_id", sa.Uuid(as_uuid=True), sa.ForeignKey("embedding_models.id"), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("chunk_id", "embedding_model_id", name="uq_document_embeddings_chunk_model"),
    )

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("started_by_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(op.f("ix_processing_jobs_document_id"), "processing_jobs", ["document_id"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Откат не поддерживается.")
