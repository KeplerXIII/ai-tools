import uuid
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from app.admin.views import (
    CategoryAdmin,
    CountryAdmin,
    DocumentAdmin,
    DocumentCategoryAdmin,
    DocumentChunkAdmin,
    DocumentEmbeddingAdmin,
    DocumentEntityAdmin,
    DocumentTagAdmin,
    DocumentTypeAdmin,
    EmbeddingModelAdmin,
    EntityAdmin,
    EntityTypeAdmin,
    EnvironmentAdmin,
    FundAdmin,
    LanguageAdmin,
    PredictionSourceAdmin,
    ProcessingJobAdmin,
    RoleAdmin,
    SourceAdmin,
    TagAdmin,
    UserAdmin,
    UserRoleAdmin,
)
from app.core.config import settings
from app.core.security import verify_password
from app.infrastructure.db.models import User
from app.infrastructure.db.session import AsyncSessionLocal, engine

_TEMPLATES_DIR = str(Path(__file__).resolve().parent / "templates")

_ADMIN_VIEWS: list[type[ModelView]] = [
    UserAdmin,
    RoleAdmin,
    UserRoleAdmin,
    LanguageAdmin,
    CountryAdmin,
    PredictionSourceAdmin,
    DocumentTypeAdmin,
    EnvironmentAdmin,
    FundAdmin,
    CategoryAdmin,
    SourceAdmin,
    DocumentAdmin,
    DocumentCategoryAdmin,
    TagAdmin,
    DocumentTagAdmin,
    EntityTypeAdmin,
    EntityAdmin,
    DocumentEntityAdmin,
    DocumentChunkAdmin,
    EmbeddingModelAdmin,
    DocumentEmbeddingAdmin,
    ProcessingJobAdmin,
]


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


_ADMIN_PANEL_ROLE_CODES = frozenset({"admin", "superuser"})


def _user_can_access_admin(user: User | None) -> bool:
    if user is None or not user.is_active:
        return False
    if user.is_admin:
        return True
    return any(getattr(r, "code", None) in _ADMIN_PANEL_ROLE_CODES for r in user.roles)


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
            result = await session.execute(
                select(User)
                .where(User.username == username)
                .options(selectinload(User.roles)),
            )
            user = result.scalar_one_or_none()
        if user is None or not _user_can_access_admin(user):
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
            result = await session.execute(
                select(User).where(User.id == uid).options(selectinload(User.roles)),
            )
            user = result.scalar_one_or_none()
        return _user_can_access_admin(user)


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
    for view in _ADMIN_VIEWS:
        admin.add_view(view)
    return admin
