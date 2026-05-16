from __future__ import annotations

from pathlib import Path

from app.services.documents.document_embedding import EmbeddingStage, split_text_for_embedding_stage
from app.services.documents.embedding_chunking import (
    count_embedding_tokens,
    get_embedding_tokenizer,
    resolve_local_tokenizer_path,
    split_text_into_token_chunks,
)


def test_get_embedding_tokenizer_loads() -> None:
    tokenizer = get_embedding_tokenizer()
    assert tokenizer.vocab_size > 0


def test_split_text_into_token_chunks_single_piece() -> None:
    assert split_text_into_token_chunks("hi", max_tokens=50) == ["hi"]


def test_split_text_into_token_chunks_multiple_windows() -> None:
    text = "word " * 200
    chunks = split_text_into_token_chunks(text, max_tokens=50, overlap_tokens=10)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert count_embedding_tokens(chunk) <= 50


def test_split_text_for_embedding_stage_uses_stage_limits(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "embedding_chunk_tokens_original", 8)
    monkeypatch.setattr(config.settings, "embedding_chunk_overlap_tokens_original", 2)
    text = "a " * 40
    chunks = split_text_for_embedding_stage(text, EmbeddingStage.ORIGINAL)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert count_embedding_tokens(chunk) <= 8


def test_resolve_local_tokenizer_path_from_hub_root(tmp_path: Path, monkeypatch) -> None:
    from app.core import config

    snap = tmp_path / "hub" / "models--BAAI--bge-m3" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "tokenizer.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(config.settings, "embedding_tokenizer_local_path", None)
    monkeypatch.setattr(config.settings, "embedding_tokenizer_hub_root", str(tmp_path / "hub"))
    monkeypatch.setattr(config.settings, "embedding_model_name", "BAAI/bge-m3")

    get_embedding_tokenizer.cache_clear()
    assert resolve_local_tokenizer_path() == str(snap)
