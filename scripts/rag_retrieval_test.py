#!/usr/bin/env -S uv run python
"""Интеграционный smoke-тест RAG retrieval (нужны DATABASE_URL, TEI, проиндексированные документы).

Пример:
  uv run python scripts/rag_retrieval_test.py "какой вопрос по базе"
  uv run python scripts/rag_retrieval_test.py "запрос" --retrieve-only
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.infrastructure.db.session import AsyncSessionLocal
from app.services.rag.rag_answer import answer_question, retrieve_for_query


async def _main(query: str, *, retrieve_only: bool, top_k: int | None) -> int:
    async with AsyncSessionLocal() as session:
        if retrieve_only:
            chunks, ms = await retrieve_for_query(session, query=query, top_k=top_k)
            print(f"retrieval_ms={ms} chunks={len(chunks)}")
            for c in chunks:
                print(
                    f"  [{c.rank}] score={c.score:.4f} doc={c.document_id} "
                    f"type={c.chunk_type} title={c.title!r}",
                )
            return 0

        result = await answer_question(session, query=query, top_k=top_k)
        print(f"retrieval_ms={result.retrieval_ms} generation_ms={result.generation_ms}")
        print("--- sources ---")
        for c in result.sources:
            print(f"  [{c.rank}] {c.title} (score={c.score:.4f})")
        print("--- answer ---")
        print(result.answer)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG smoke test")
    parser.add_argument("query", help="Текст запроса")
    parser.add_argument("--retrieve-only", action="store_true")
    parser.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_main(args.query, retrieve_only=args.retrieve_only, top_k=args.top_k)))


if __name__ == "__main__":
    main()
