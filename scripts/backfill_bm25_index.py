#!/usr/bin/env -S uv run python
"""Обёртка: ``uv run python -m app.cli.backfill_bm25_index`` (предпочтительно)."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if __name__ == "__main__":
    runpy.run_module("app.cli.backfill_bm25_index", run_name="__main__")
