from fastapi import HTTPException

from app.domain.errors import (
    AppError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    InvalidProviderResponseError,
    NotFoundError,
    ValidationError,
)


def map_app_error(exc: AppError) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))

    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))

    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))

    if isinstance(exc, ForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))

    if isinstance(exc, (ExternalServiceError, InvalidProviderResponseError)):
        return HTTPException(status_code=502, detail=str(exc))

    return HTTPException(status_code=500, detail="Внутренняя ошибка приложения")
