"""Нарезка текста для эмбеддингов по токенам tokenizer модели (как в TEI/bge-m3)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from transformers import AutoTokenizer

from app.core.config import settings

if TYPE_CHECKING:
    from transformers import PreTrainedTokenizerBase

_log = logging.getLogger(__name__)


def _hub_model_dir(hub_root: Path, model_name: str) -> Path:
    return hub_root / f"models--{model_name.replace('/', '--')}"


def _snapshot_has_tokenizer(snapshot_dir: Path) -> bool:
    return (snapshot_dir / "tokenizer.json").is_file() or (
        snapshot_dir / "tokenizer_config.json"
    ).is_file()


def resolve_local_tokenizer_path(*, model_name: str | None = None) -> str | None:
    """Путь к локальному snapshot без записи в hub (read-only том TEI)."""
    explicit = (settings.embedding_tokenizer_local_path or "").strip()
    if explicit:
        path = Path(explicit)
        return str(path) if path.is_dir() and _snapshot_has_tokenizer(path) else None

    hub_root_raw = (settings.embedding_tokenizer_hub_root or "").strip()
    if not hub_root_raw:
        return None

    hub_root = Path(hub_root_raw)
    if not hub_root.is_dir():
        return None

    name = model_name or settings.embedding_model_name
    snapshots = _hub_model_dir(hub_root, name) / "snapshots"
    if not snapshots.is_dir():
        return None

    candidates = sorted(
        (p for p in snapshots.iterdir() if p.is_dir() and _snapshot_has_tokenizer(p)),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


@lru_cache(maxsize=2)
def get_embedding_tokenizer(model_name: str | None = None) -> PreTrainedTokenizerBase:
    name = model_name or settings.embedding_model_name
    local_path = resolve_local_tokenizer_path(model_name=name)
    if local_path:
        _log.debug("embedding tokenizer from local snapshot %s", local_path)
        return AutoTokenizer.from_pretrained(local_path, local_files_only=True)

    kwargs: dict[str, object] = {}
    if settings.embedding_tokenizer_cache_dir:
        kwargs["cache_dir"] = settings.embedding_tokenizer_cache_dir
    if settings.embedding_tokenizer_local_files_only:
        kwargs["local_files_only"] = True
    return AutoTokenizer.from_pretrained(name, **kwargs)


def count_embedding_tokens(text: str, *, model_name: str | None = None) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    tokenizer = get_embedding_tokenizer(model_name)
    return len(tokenizer.encode(stripped, add_special_tokens=False))


def split_text_into_token_chunks(
    text: str,
    *,
    max_tokens: int,
    overlap_tokens: int = 0,
    model_name: str | None = None,
) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    tokenizer = get_embedding_tokenizer(model_name)
    tokens = tokenizer.encode(stripped, add_special_tokens=False)
    if len(tokens) <= max_tokens:
        return [stripped]
    overlap = min(max(overlap_tokens, 0), max_tokens - 1)
    step = max_tokens - overlap
    out: list[str] = []
    start = 0
    while start < len(tokens):
        piece_ids = tokens[start : start + max_tokens]
        out.append(
            tokenizer.decode(
                piece_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ),
        )
        if start + max_tokens >= len(tokens):
            break
        start += step
    return out
