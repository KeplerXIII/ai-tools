class AppError(Exception):
    """Base application error."""


class ValidationError(AppError):
    """Raised when user input is invalid for a use case."""


class ExternalServiceError(AppError):
    """Raised when external provider call fails."""


class InvalidProviderResponseError(AppError):
    """Raised when provider returns malformed response."""


class NotFoundError(AppError):
    """Ресурс не найден."""


class ConflictError(AppError):
    """Конфликт состояния (например, блокировка)."""


class ForbiddenError(AppError):
    """Действие запрещено для текущего пользователя."""
