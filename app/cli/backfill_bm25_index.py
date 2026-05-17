"""Заполнить document_chunk_terms для уже существующих чанков (BM25).

С хоста (``DATABASE_URL_FOR_CLI`` при необходимости):

  uv run python -m app.cli.backfill_bm25_index
  uv run python -m app.cli.backfill_bm25_index --batch-size 200

В контейнере:

  docker compose exec ai-tools uv run python -m app.cli.backfill_bm25_index
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.infrastructure.db.models import DocumentChunk
from app.infrastructure.db.session import AsyncSessionLocal
from app.services.rag.bm25_index import sync_bm25_terms_for_chunk


async def _run(batch_size: int) -> int:
    async with AsyncSessionLocal() as session:
        offset = 0
        total = 0
        while True:
            rows = (
                await session.execute(
                    select(DocumentChunk.id, DocumentChunk.content)
                    .order_by(DocumentChunk.id)
                    .limit(batch_size)
                    .offset(offset),
                )
            ).all()
            if not rows:
                break
            for chunk_id, content in rows:
                await sync_bm25_terms_for_chunk(
                    session,
                    chunk_id=chunk_id,
                    content=content or "",
                )
                total += 1
            await session.commit()
            offset += batch_size
            print(f"indexed {total} chunks…", flush=True)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill BM25 term index")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    total = asyncio.run(_run(args.batch_size))
    print(f"done: {total} chunks")


if __name__ == "__main__":
    main()
