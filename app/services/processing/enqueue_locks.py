from __future__ import annotations

from redis import asyncio as aioredis

from app.core.config import settings

_KEY_PREFIX = "processing:enqueue_lock:"


def _lock_key(kind: str, document_id: str) -> str:
    return f"{_KEY_PREFIX}{kind}:{document_id}"


async def try_acquire_enqueue_lock(kind: str, document_id: str, *, ttl_sec: int) -> bool:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _lock_key(kind, document_id)
    try:
        # set nx ex => acquire only if absent, with expiration safety.
        ok = await redis.set(key, "1", ex=max(60, ttl_sec), nx=True)
        return bool(ok)
    finally:
        await redis.aclose()


async def release_enqueue_lock(kind: str, document_id: str) -> None:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _lock_key(kind, document_id)
    try:
        await redis.delete(key)
    finally:
        await redis.aclose()
