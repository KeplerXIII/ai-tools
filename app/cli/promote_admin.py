"""Назначить пользователю is_admin и роль admin (вход в SQLAdmin по /admin).

  uv run python -m app.cli.promote_admin USERNAME

В Docker:

  docker compose exec ai-tools uv run python -m app.cli.promote_admin USERNAME
"""

import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.infrastructure.db.models import Role, User, UserRole
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
            select(User).where(User.username == username).options(selectinload(User.roles)),
        )
        user = result.scalar_one_or_none()
        if user is None:
            print(f"Пользователь «{username}» не найден", file=sys.stderr)
            sys.exit(1)
        user.is_admin = True
        role_row = await session.execute(select(Role).where(Role.code == "admin"))
        role = role_row.scalar_one_or_none()
        if role is not None:
            link = await session.execute(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role_id == role.id,
                ),
            )
            if link.scalar_one_or_none() is None:
                session.add(UserRole(user_id=user.id, role_id=role.id))
        await session.commit()
    print(f"OK: «{username}» теперь администратор (SQLAdmin /admin) и роль admin в user_roles")


if __name__ == "__main__":
    asyncio.run(main())
