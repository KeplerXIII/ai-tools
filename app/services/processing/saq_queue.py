from __future__ import annotations

from saq import Queue

from app.core.config import settings


def get_saq_translate_queue() -> Queue:
    return Queue.from_url(
        settings.saq_queue_url,
        name=settings.saq_translate_queue_name,
    )


def get_saq_annotate_queue() -> Queue:
    return Queue.from_url(
        settings.saq_queue_url,
        name=settings.saq_annotate_queue_name,
    )
