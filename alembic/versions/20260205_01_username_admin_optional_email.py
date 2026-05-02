"""username, is_admin; email nullable

Revision ID: 20260205_01
Revises:
Create Date: 2026-02-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20260205_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )
        op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
        op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)
        return

    cols = {c["name"] for c in inspector.get_columns("users")}
    if "username" not in cols:
        op.add_column("users", sa.Column("username", sa.String(length=64), nullable=True))
        op.add_column(
            "users",
            sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column(
            "users",
            "email",
            existing_type=sa.String(length=320),
            nullable=True,
        )
        op.execute(
            sa.text(
                "UPDATE users SET username = 'u' || replace(id::text, '-', '') "
                "WHERE username IS NULL"
            )
        )
        op.alter_column("users", "username", existing_type=sa.String(length=64), nullable=False)
        op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)


def downgrade() -> None:
    raise NotImplementedError(
        "Откат этой миграции не поддерживается; при необходимости восстановите БД из бэкапа."
    )
