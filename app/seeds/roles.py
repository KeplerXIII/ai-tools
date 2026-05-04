"""Роли и связь ``user_roles`` для пользователей с ``is_admin``."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import Role
from app.seeds.util import rows_with_fresh_uuids

STANDARD_ROLES: list[dict[str, Any]] = [
    {
        "code": "admin",
        "name": "Администратор",
        "description": "Полный доступ к SQLAdmin и служебным операциям",
    },
    {
        "code": "superuser",
        "name": "Суперпользователь",
        "description": "Расширенные права в приложении; вход в SQLAdmin",
    },
    {
        "code": "user",
        "name": "Пользователь",
        "description": "Базовый доступ",
    },
]


async def apply_roles_seed(session: AsyncSession) -> int:
    rows = rows_with_fresh_uuids(STANDARD_ROLES)
    stmt = insert(Role).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Role.code],
        set_={
            "name": stmt.excluded.name,
            "description": stmt.excluded.description,
        },
    )
    await session.execute(stmt)
    return len(STANDARD_ROLES)


async def apply_user_admin_roles(session: AsyncSession) -> None:
    admin_id = await session.scalar(select(Role.id).where(Role.code == "admin"))
    if admin_id is None:
        return
    await session.execute(
        text(
            """
            INSERT INTO user_roles (user_id, role_id)
            SELECT u.id, :rid
            FROM users u
            WHERE u.is_admin = true
            ON CONFLICT (user_id, role_id) DO NOTHING
            """
        ),
        {"rid": admin_id},
    )
