import uuid

from fastapi import FastAPI
from sqlalchemy import select
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from app.core.config import settings
from app.core.security import verify_password
from app.infrastructure.db.models import User
from app.infrastructure.db.session import AsyncSessionLocal, engine


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        raw_u = form.get("username")
        raw_p = form.get("password")
        username = (raw_u if isinstance(raw_u, str) else "").strip().lower()
        password = raw_p if isinstance(raw_p, str) else ""
        if not username or not password:
            return False
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
        if user is None or not user.is_active or not user.is_admin:
            return False
        if not verify_password(password, user.hashed_password):
            return False
        request.session["admin_id"] = str(user.id)
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        admin_id = request.session.get("admin_id")
        if not admin_id:
            return False
        try:
            uid = uuid.UUID(str(admin_id))
        except (ValueError, TypeError):
            return False
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(User).where(User.id == uid))
            user = result.scalar_one_or_none()
        return bool(user and user.is_active and user.is_admin)


class UserAdmin(ModelView, model=User):
    name = "Пользователь"
    name_plural = "Пользователи"
    icon = "fa-solid fa-user"
    column_list = [User.id, User.username, User.email, User.is_active, User.is_admin, User.created_at]
    column_searchable_list = [User.username, User.email]
    column_sortable_list = [User.username, User.created_at]
    form_excluded_columns = [User.hashed_password, User.id, User.created_at]
    can_create = False
    can_delete = True


def mount_admin(app: FastAPI) -> Admin:
    secret = settings.admin_session_secret or settings.jwt_secret_key
    authentication_backend = AdminAuth(secret_key=secret)
    admin = Admin(
        app,
        engine,
        authentication_backend=authentication_backend,
        base_url="/admin",
        title=f"{settings.app_name} — админка",
    )
    admin.add_view(UserAdmin)
    return admin
