"""Общие утилиты для сидов."""

from __future__ import annotations

import uuid
from typing import Any


def rows_with_fresh_uuids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SQLAlchemy bulk insert иначе подставляет id=NULL; для PK нужен явный uuid."""
    return [{**r, "id": uuid.uuid4()} for r in rows]
