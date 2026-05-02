"""Назначить пользователю is_admin (вход в SQLAdmin по /admin).

  uv run python -m app.cli.promote_admin USERNAME

В Docker:

  docker compose exec ai-tools uv run python -m app.cli.promote_admin USERNAME
"""

import asyncio
import sys

from sqlalchemy import update

from app.infrastructure.db.models import User
from app.infrastructure.db.session import AsyncSessionLocal


async def main() -> None:
    if len(sys.argv) != 2:
        print(
            "Usage: uv run python -m app.cli.promote_admin <username>",
            file=sys.stderr,
        )
        sys.exit(1)
    username = sys.argv[1].strip().lower()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            update(User).where(User.username == username).values(is_admin=True),
        )
        await session.commit()
        n = result.rowcount
    if not n:
        print(f"Пользователь «{username}» не найден", file=sys.stderr)
        sys.exit(1)
    print(f"OK: «{username}» теперь администратор (SQLAdmin /admin)")


if __name__ == "__main__":
    asyncio.run(main())
