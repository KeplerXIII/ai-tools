from __future__ import annotations

import json
from typing import Any


def sse_json_event(event: str, payload: dict[str, Any]) -> bytes:
    """Один SSE-фрейм: ``event`` + JSON в ``data`` (как в processing / parsing)."""
    data = json.dumps(payload, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")
