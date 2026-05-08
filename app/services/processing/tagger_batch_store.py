from __future__ import annotations

from redis import asyncio as aioredis

from app.core.config import settings

_KEY_PREFIX = "processing:tagger_batch:"
_TTL_SEC = 7 * 24 * 60 * 60


def _batch_key(batch_id: str) -> str:
    return f"{_KEY_PREFIX}{batch_id}"


async def init_tagger_batch(batch_id: str, *, scanned: int) -> None:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _batch_key(batch_id)
    try:
        await redis.hset(
            key,
            mapping={
                "scanned": str(scanned),
                "enqueued": "0",
                "completed": "0",
                "failed": "0",
                "skipped": "0",
            },
        )
        await redis.expire(key, _TTL_SEC)
    finally:
        await redis.aclose()


async def inc_tagger_batch_counter(batch_id: str, field: str) -> None:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _batch_key(batch_id)
    try:
        await redis.hincrby(key, field, 1)
        await redis.expire(key, _TTL_SEC)
    finally:
        await redis.aclose()


async def get_tagger_batch(batch_id: str) -> dict[str, int] | None:
    redis = aioredis.from_url(settings.saq_queue_url, encoding="utf-8", decode_responses=True)
    key = _batch_key(batch_id)
    try:
        payload = await redis.hgetall(key)
    finally:
        await redis.aclose()

    if not payload:
        return None

    return {
        "scanned": int(payload.get("scanned", "0")),
        "enqueued": int(payload.get("enqueued", "0")),
        "completed": int(payload.get("completed", "0")),
        "failed": int(payload.get("failed", "0")),
        "skipped": int(payload.get("skipped", "0")),
    }
