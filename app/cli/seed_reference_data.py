"""Заливает все справочники через ``app/seeds/reference_data.py`` (идемпотентно).

После ``alembic upgrade head`` / ``init_db``:

  uv run python -m app.cli.seed_reference_data

С хоста при docker-хосте в ``.env``:

  DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/DB' \\
    uv run python -m app.cli.seed_reference_data

Включает: roles, languages, countries (ISO 3166-1 через pycountry), prediction_sources,
entity_types, embedding_models, environments, funds, categories, document_types,
а также связь ``user_roles`` для пользователей с ``is_admin``.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.cli.database_url import async_database_url_for_cli
from app.seeds.reference_data import seed_reference_catalog


async def main() -> None:
    engine = create_async_engine(async_database_url_for_cli(), echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with session_factory() as session:
            counts = await seed_reference_catalog(session)
            await session.commit()
    finally:
        await engine.dispose()
    parts = [f"{k}={v}" for k, v in counts.items()]
    print(f"OK: reference data — {', '.join(parts)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
