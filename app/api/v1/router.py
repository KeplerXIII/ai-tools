from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.api.v1.endpoints import auth, documents, extract, health, parsing, translate

api_router = APIRouter(prefix="/api/v1")

_require_user = [Depends(get_current_user)]

api_router.include_router(health.router, dependencies=_require_user)
api_router.include_router(auth.router)
api_router.include_router(extract.router, dependencies=_require_user)
api_router.include_router(translate.router, dependencies=_require_user)
api_router.include_router(documents.router, dependencies=_require_user)
api_router.include_router(parsing.router)