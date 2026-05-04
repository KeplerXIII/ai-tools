"""Заполняет справочник ``document_types`` стандартными кодами (идемпотентно).

  uv run python -m app.cli.seed_document_types

В Docker (образ должен содержать актуальный код) после миграций:

  docker compose exec ai-tools uv run python -m app.cli.seed_document_types

Для полного набора справочников предпочтительнее ``python -m app.cli.seed_reference_data``.

С хоста, если в ``.env`` указан docker-хост БД, задайте URL на ``127.0.0.1``:

  DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/DB' \\
    uv run python -m app.cli.seed_document_types

При совпадении ``code`` обновляются ``name`` и ``description``; первичный ключ
для новой строки — случайный UUID, для уже существующей записи не меняется.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cli.database_url import async_database_url_for_cli
from app.seeds.document_types import apply_document_types_seed


async def main() -> None:
    engine = create_async_engine(async_database_url_for_cli(), echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            n = await apply_document_types_seed(session)
            await session.commit()
    finally:
        await engine.dispose()
    print(f"OK: document_types — {n} записей (upsert по code)")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
