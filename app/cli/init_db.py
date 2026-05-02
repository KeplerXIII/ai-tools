"""Применяет схему БД через Alembic (``alembic upgrade head``).

Один поддерживаемый путь: миграции. Эта команда — удобная обёртка (то же, что
``uv run alembic upgrade head`` из корня репозитория, где лежит ``alembic.ini``).

С хоста, если в ``DATABASE_URL`` указан docker-hostname БД (например
``ai-tools-postgres``), а Postgres доступен на ``127.0.0.1:5432``:

  DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/DB' \\
    uv run python -m app.cli.init_db

Переменная ``DATABASE_URL_FOR_CLI`` учитывается и здесь, и в ``alembic/env.py``.

В контейнере приложения:

  docker compose exec ai-tools uv run python -m app.cli.init_db
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    root = _project_root()
    ini = root / "alembic.ini"
    if not ini.is_file():
        sys.stderr.write(f"init_db: не найден {ini}\n")
        raise SystemExit(1)

    env = os.environ.copy()
    # pydantic-settings уже подхватил .env; DATABASE_URL_FOR_CLI задаётся в shell при необходимости
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root,
            env=env,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(
            "\ninit_db: ``alembic upgrade head`` завершился с ошибкой.\n"
            "  • Запустите из контейнера ``ai-tools``, если БД доступна только по docker DNS.\n"
            "  • С хоста попробуйте:\n"
            "    DATABASE_URL_FOR_CLI='postgresql+asyncpg://USER:PASS@127.0.0.1:5432/aitools' "
            "uv run python -m app.cli.init_db\n\n"
        )
        raise SystemExit(exc.returncode) from exc


if __name__ == "__main__":
    main()
