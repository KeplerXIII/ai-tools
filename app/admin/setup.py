import uuid
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from wtforms import PasswordField
from wtforms.validators import Length, Optional

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.infrastructure.db.models import User
from app.infrastructure.db.session import AsyncSessionLocal, engine

_TEMPLATES_DIR = str(Path(__file__).resolve().parent / "templates")


class AdminRu(Admin):
    """Та же админка, но сообщение при ошибке входа на русском."""

    async def login(self, request: Request) -> Response:
        if self.authentication_backend is None:
            raise HTTPException(
                status_code=503,
                detail="Authentication backend not configured.",
            )

        context: dict = {}
        if request.method == "GET":
            return await self.templates.TemplateResponse(request, "sqladmin/login.html")

        ok = await self.authentication_backend.login(request)
        if not ok:
            context["error"] = "Неверный логин или пароль."
            return await self.templates.TemplateResponse(
                request, "sqladmin/login.html", context, status_code=400
            )

        return RedirectResponse(request.url_for("admin:index"), status_code=302)


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
    column_labels = {
        User.id: "ID",
        User.username: "Логин",
        User.email: "Email",
        User.hashed_password: "Пароль (хэш)",
        User.is_active: "Активен",
        User.is_admin: "Администратор",
        User.created_at: "Создан",
    }
    column_list = [User.id, User.username, User.email, User.is_active, User.is_admin, User.created_at]
    column_searchable_list = [User.username, User.email]
    column_sortable_list = [User.username, User.created_at]
    form_columns = [User.username, User.email, User.hashed_password, User.is_active, User.is_admin]
    form_overrides = {"hashed_password": PasswordField}
    form_args = {
        "username": {"label": "Логин"},
        "email": {"label": "Email"},
        "is_active": {"label": "Активен"},
        "is_admin": {"label": "Администратор"},
        "hashed_password": {
            "label": "Пароль",
            "description": "При создании — обязательно (от 8 символов). При редактировании оставьте пустым, чтобы не менять.",
            "validators": [Optional(), Length(min=8, max=128)],
        }
    }
    can_create = True
    can_delete = True

    async def on_model_change(
        self,
        data: dict,
        model: User,
        is_created: bool,
        request: Request,
    ) -> None:
        if "username" in data and isinstance(data["username"], str):
            data["username"] = data["username"].strip().lower()

        if data.get("email") == "":
            data["email"] = None

        raw_pw = data.get("hashed_password")
        if isinstance(raw_pw, str):
            raw_pw = raw_pw.strip()
        else:
            raw_pw = ""

        if raw_pw:
            data["hashed_password"] = hash_password(raw_pw)
        else:
            data.pop("hashed_password", None)
            if is_created:
                raise ValueError("При создании пользователя укажите пароль (не короче 8 символов).")


def mount_admin(app: FastAPI) -> Admin:
    secret = settings.admin_session_secret or settings.jwt_secret_key
    authentication_backend = AdminAuth(secret_key=secret)
    admin = AdminRu(
        app,
        engine,
        authentication_backend=authentication_backend,
        base_url="/admin",
        title=f"{settings.app_name} — админка",
        templates_dir=_TEMPLATES_DIR,
    )
    admin.add_view(UserAdmin)
    return admin
