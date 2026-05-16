from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.services.documents.document_embedding import (
    EmbeddingStage,
    _annotation_embed_text,
    content_fingerprint,
    embed_document_if_stale,
    is_embedding_fresh,
)


def test_content_fingerprint_normalizes_whitespace() -> None:
    assert content_fingerprint("a  b") == content_fingerprint("a b")


def test_is_embedding_fresh_when_fp_matches() -> None:
    class Doc:
        original_content = "hello world"
        original_language_id = uuid.uuid4()
        translated_content = None
        translated_language_id = None
        translated_summary = None
        original_summary = None
        embedding_original_fp = content_fingerprint("hello world")
        embedding_translated_fp = None
        embedding_annotation_fp = None

    assert is_embedding_fresh(Doc(), EmbeddingStage.ORIGINAL) is True  # type: ignore[arg-type]
    assert is_embedding_fresh(Doc(), EmbeddingStage.TRANSLATED) is False  # type: ignore[arg-type]


def test_annotation_embed_text_prefers_both_summaries() -> None:
    class Doc:
        translated_summary = "ru"
        original_summary = "en"

    assert "ru" in _annotation_embed_text(Doc())  # type: ignore[arg-type]
    assert "en" in _annotation_embed_text(Doc())  # type: ignore[arg-type]


def test_embed_runs_when_fp_matches_but_chunks_missing() -> None:
    lang_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    class Doc:
        id = doc_id
        original_content = "hello"
        original_language_id = lang_id
        translated_content = None
        translated_language_id = None
        translated_summary = None
        original_summary = None
        embedding_original_fp = content_fingerprint("hello")
        embedding_translated_fp = None
        embedding_annotation_fp = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=Doc())
    session.scalar = AsyncMock(return_value=0)

    with (
        patch("app.services.documents.document_embedding.settings") as mock_settings,
        patch(
            "app.services.documents.document_embedding.create_embeddings",
            new_callable=AsyncMock,
            return_value=[[0.1] * 1024],
        ),
        patch(
            "app.services.documents.document_embedding._embedding_model_id",
            new_callable=AsyncMock,
            return_value=uuid.uuid4(),
        ),
    ):
        mock_settings.embedding_enabled = True
        mock_settings.embedding_chunk_tokens_original = 100_000
        mock_settings.embedding_chunk_overlap_tokens_original = 0
        mock_settings.embedding_chunk_tokens_translated = 100_000
        mock_settings.embedding_chunk_overlap_tokens_translated = 0
        mock_settings.embedding_chunk_tokens_annotation = 100_000
        mock_settings.embedding_chunk_overlap_tokens_annotation = 0
        mock_settings.embedding_fail_open = False
        result = asyncio.run(
            embed_document_if_stale(
                session,
                document_id=doc_id,
                stage=EmbeddingStage.ORIGINAL,
            ),
        )

    assert result.status == "embedded"
    assert session.scalar.await_count >= 1


def test_embed_skips_when_fp_matches() -> None:
    class Doc:
        id = uuid.uuid4()
        original_content = "hello"
        original_language_id = uuid.uuid4()
        translated_content = None
        translated_language_id = None
        translated_summary = None
        original_summary = None
        embedding_original_fp = content_fingerprint("hello")
        embedding_translated_fp = None
        embedding_annotation_fp = None

    session = AsyncMock()
    session.get = AsyncMock(return_value=Doc())
    session.scalar = AsyncMock(return_value=1)

    with patch("app.services.documents.document_embedding.settings") as mock_settings:
        mock_settings.embedding_enabled = True
        result = asyncio.run(
            embed_document_if_stale(
                session,
                document_id=Doc.id,
                stage=EmbeddingStage.ORIGINAL,
            ),
        )

    assert result.status == "skipped_current"
    session.execute.assert_not_called()
