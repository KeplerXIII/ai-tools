from __future__ import annotations

from saq import Queue

from app.core.config import settings


def get_saq_queue() -> Queue:
    return Queue.from_url(
        settings.saq_queue_url,
        name=settings.saq_queue_name,
    )
