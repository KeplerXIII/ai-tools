"""Создаёт таблицы в PostgreSQL по моделям SQLAlchemy (без Alembic).

Запуск из корня репозитория (при DATABASE_URL с хостом ai-tools-postgres это
работает только внутри Docker-сети; с хоста см. ниже):

  uv run python -m app.cli.init_db

В контейнере приложения (тот же хост БД, что и у API):

  docker compose exec ai-tools uv run python -m app.cli.init_db

С хоста, если порт Postgres проброшен на 127.0.0.1:5432 — одноразово подставьте URL:

  DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/DB' uv run python -m app.cli.init_db

Если задана переменная DATABASE_URL_FOR_CLI, она используется вместо DATABASE_URL
(удобно, чтобы не менять основной URL для Docker).
"""

import asyncio
import os
import socket
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import User  # noqa: F401 — регистрация модели в metadata


def _database_url() -> str:
    return os.environ.get("DATABASE_URL_FOR_CLI", "").strip() or settings.database_url


async def main() -> None:
    url = _database_url()
    engine = create_async_engine(url, echo=settings.debug)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except socket.gaierror as exc:
        sys.stderr.write(
            "\ninit_db: не удалось разрешить имя хоста в URL БД "
            f"({exc}).\n"
            "  • Запустите из контейнера: "
            "docker compose exec ai-tools uv run python -m app.cli.init_db\n"
            "  • Или с хоста укажите localhost, например:\n"
            "    DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/aitools' "
            "uv run python -m app.cli.init_db\n\n"
        )
        raise SystemExit(1) from exc
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
