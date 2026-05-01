from fastapi import HTTPException

from app.domain.errors import (
    AppError,
    ExternalServiceError,
    InvalidProviderResponseError,
    ValidationError,
)


def map_app_error(exc: AppError) -> HTTPException:
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))

    if isinstance(exc, (ExternalServiceError, InvalidProviderResponseError)):
        return HTTPException(status_code=502, detail=str(exc))

    return HTTPException(status_code=500, detail="Внутренняя ошибка приложения")
