"""Структурированные ошибки экстракта: один формат detail, разные HTTP-статусы."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from requests import Response
from requests.exceptions import (
    ChunkedEncodingError,
    ConnectionError,
    ContentDecodingError,
    HTTPError,
    InvalidSchema,
    InvalidURL,
    RequestException,
    SSLError,
    Timeout,
    TooManyRedirects,
)


def extract_error_detail(
    *,
    code: str,
    stage: str,
    message: str,
    hint: str | None = None,
    upstream_http_status: int | None = None,
    technical: str | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "error": code,
        "stage": stage,
        "message": message,
    }
    if hint:
        d["hint"] = hint
    if upstream_http_status is not None:
        d["upstream_http_status"] = upstream_http_status
    if technical:
        d["technical"] = technical
    return d


def _upstream_line(resp: Response | None) -> str:
    if resp is None:
        return ""
    reason = (getattr(resp, "reason", None) or "").strip()
    if reason:
        return f"HTTP {resp.status_code} {reason}"
    return f"HTTP {resp.status_code}"


def http_exception_for_http_error(exc: HTTPError, *, stage: str = "http_fetch") -> HTTPException:
    """Ответ целевого сайта с кодом 4xx/5xx после исчерпания ретраев."""
    resp = exc.response
    u = resp.status_code if resp is not None else None
    line = _upstream_line(resp)

    if u is None:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=extract_error_detail(
                code="FETCH_HTTP_ERROR",
                stage=stage,
                message="Сайт вернул ответ с ошибкой, но без кода состояния.",
                technical=str(exc),
            ),
        )

    if u >= 500:
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=extract_error_detail(
                code="FETCH_UPSTREAM_5XX",
                stage=stage,
                message=f"Сервер сайта ответил ошибкой ({line}). Попробуйте позже.",
                upstream_http_status=u,
                hint="Это ответ удалённого сервера, не вашего API.",
                technical=str(exc),
            ),
        )

    messages = {
        400: "Некорректный запрос — сайт отклонил обращение.",
        401: "Сайт требует авторизацию для этого URL.",
        403: "Доступ запрещён. Часто так блокируют простые HTTP-клиенты и ботов.",
        404: "Страница по этому адресу не найдена (404).",
        405: "Метод запроса не поддерживается для этого URL.",
        408: "Сайт не дождался запроса (таймаут на стороне сайта).",
        410: "Ресурс удалён (410).",
        429: "Сайт ограничил частоту запросов (429). Подождите и повторите.",
    }
    base = messages.get(u, f"Сайт отклонил запрос ({line}).")

    return HTTPException(
        status_code=status.HTTP_424_FAILED_DEPENDENCY,
        detail=extract_error_detail(
            code=f"FETCH_HTTP_{u}",
            stage=stage,
            message=base,
            upstream_http_status=u,
            hint="Проверьте URL в браузере. Для закрытых страниц экстракт может быть недоступен.",
            technical=str(exc),
        ),
    )


def http_exception_for_timeout(exc: Timeout, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=extract_error_detail(
            code="FETCH_TIMEOUT",
            stage=stage,
            message="Превышено время ожидания ответа от сайта.",
            hint="Сайт долго не отвечает или ответ слишком большой. Увеличьте REQUEST_TIMEOUT или повторите позже.",
            technical=str(exc),
        ),
    )


def http_exception_for_ssl(exc: SSLError, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_SSL_ERROR",
            stage=stage,
            message="Не удалось установить защищённое соединение (SSL/TLS) с сайтом.",
            hint="На стороне сайта может быть просроченный сертификат или нестандартная цепочка доверия.",
            technical=str(exc),
        ),
    )


def http_exception_for_connection(exc: ConnectionError, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_CONNECTION_ERROR",
            stage=stage,
            message="Не удалось подключиться к сайту (сеть, DNS или сервер не принимает соединение).",
            hint="Проверьте, что хост существует и доступен из сети, где запущен сервис.",
            technical=str(exc),
        ),
    )


def http_exception_for_chunked(exc: ChunkedEncodingError, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_INCOMPLETE_RESPONSE",
            stage=stage,
            message="Ответ сайта оборвался при передаче (некорректный chunked/stream).",
            technical=str(exc),
        ),
    )


def http_exception_for_decode(exc: ContentDecodingError, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_DECODE_ERROR",
            stage=stage,
            message="Не удалось разобрать сжатый или закодированный ответ сайта.",
            technical=str(exc),
        ),
    )


def http_exception_for_invalid_url(exc: InvalidURL | InvalidSchema, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=extract_error_detail(
            code="FETCH_INVALID_URL",
            stage=stage,
            message="Некорректный или неподдерживаемый URL для загрузки.",
            technical=str(exc),
        ),
    )


def http_exception_for_request(exc: RequestException, *, stage: str = "http_fetch") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_ERROR",
            stage=stage,
            message="Ошибка при загрузке страницы.",
            technical=str(exc),
        ),
    )


def map_request_exception(exc: BaseException, *, stage: str = "http_fetch") -> HTTPException:
    if isinstance(exc, HTTPError):
        return http_exception_for_http_error(exc, stage=stage)
    if isinstance(exc, TooManyRedirects):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=extract_error_detail(
                code="FETCH_TOO_MANY_REDIRECTS",
                stage=stage,
                message="Слишком много перенаправлений при загрузке URL.",
                technical=str(exc),
            ),
        )
    if isinstance(exc, Timeout):
        return http_exception_for_timeout(exc, stage=stage)
    if isinstance(exc, SSLError):
        return http_exception_for_ssl(exc, stage=stage)
    if isinstance(exc, ChunkedEncodingError):
        return http_exception_for_chunked(exc, stage=stage)
    if isinstance(exc, ContentDecodingError):
        return http_exception_for_decode(exc, stage=stage)
    if isinstance(exc, (InvalidURL, InvalidSchema)):
        return http_exception_for_invalid_url(exc, stage=stage)
    if isinstance(exc, ConnectionError):
        return http_exception_for_connection(exc, stage=stage)
    if isinstance(exc, RequestException):
        return http_exception_for_request(exc, stage=stage)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="FETCH_UNKNOWN_ERROR",
            stage=stage,
            message="Неожиданная ошибка при загрузке страницы.",
            technical=str(exc),
        ),
    )


def http_exception_playwright_timeout(*, stage: str = "playwright_render") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        detail=extract_error_detail(
            code="PLAYWRIGHT_TIMEOUT",
            stage=stage,
            message="Таймаут: страница не успела загрузиться в браузере (Playwright).",
            hint="Сайт может быть тяжёлым или зависеть от долгих запросов. Увеличьте REQUEST_TIMEOUT.",
        ),
    )


def http_exception_playwright_failed(exc: BaseException, *, stage: str = "playwright_render") -> HTTPException:
    text = str(exc).strip()
    hint = None
    if "Executable doesn't exist" in text or "BrowserType.launch" in text:
        hint = "В окружении не установлен браузер Chromium для Playwright (нужен `playwright install chromium`)."
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=extract_error_detail(
            code="PLAYWRIGHT_ERROR",
            stage=stage,
            message="Ошибка рендера страницы в браузере (Playwright).",
            hint=hint,
            technical=text or repr(exc),
        ),
    )


def http_exception_extract_empty(*, had_url: bool) -> HTTPException:
    hint = (
        "Передайте полный URL в запросе /extract/html, чтобы сработал рендер через Playwright для JS-сайтов."
        if not had_url
        else "Контент может подгружаться только после действий пользователя или быть в нестандартной вёрстке."
    )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=extract_error_detail(
            code="EXTRACT_NO_MAIN_TEXT",
            stage="extract",
            message="Не удалось извлечь содержательный текст статьи из HTML.",
            hint=hint,
        ),
    )
