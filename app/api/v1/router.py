from fastapi import APIRouter

from app.api.v1.endpoints import extract, health, translate

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(health.router)
api_router.include_router(extract.router)
api_router.include_router(translate.router)