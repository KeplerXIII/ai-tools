import time

import requests
import trafilatura
from bs4 import BeautifulSoup
from fastapi import HTTPException
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from app.core.config import settings

from .extract_errors import (
    http_exception_extract_empty,
    http_exception_for_http_error,
    http_exception_playwright_failed,
    http_exception_playwright_timeout,
    map_request_exception,
)
from .image_extractor import extract_images, pick_main_image
from .extract_logging import logger, url_host, url_preview
from .playwright_overlays import settle_after_navigation


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


# ======================
# HTML CLEANER
# ======================
def shrink_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()

    return str(soup)


# ======================
# REQUESTS
# ======================
def download_html(url: str) -> str:
    """Скачивает HTML с ретраями при обрыве сети и 502/503/504 у целевого сервера."""
    attempts = 3
    backoff = 0.6

    logger.info(
        {
            "event": "extract_fetch_request",
            "url_preview": url_preview(url),
            "host": url_host(url),
            "timeout_sec": settings.request_timeout,
            "max_attempts": attempts,
        }
    )

    for attempt in range(attempts):
        try:
            response = requests.get(
                url,
                timeout=settings.request_timeout,
                headers=BROWSER_HEADERS,
            )
            response.raise_for_status()
            html = response.text
            logger.info(
                {
                    "event": "extract_fetch_success",
                    "url_preview": url_preview(url),
                    "host": url_host(url),
                    "html_chars": len(html),
                    "attempt": attempt + 1,
                }
            )
            return html
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if (
                code in (502, 503, 504)
                and attempt < attempts - 1
            ):
                logger.warning(
                    {
                        "event": "extract_fetch_retry",
                        "url_preview": url_preview(url),
                        "host": url_host(url),
                        "attempt": attempt + 1,
                        "reason": f"upstream_http_{code}",
                    }
                )
                time.sleep(backoff * (attempt + 1))
                continue
            err = http_exception_for_http_error(exc)
            logger.error(
                {
                    "event": "extract_fetch_error",
                    "url_preview": url_preview(url),
                    "host": url_host(url),
                    "attempt": attempt + 1,
                    "status_code": err.status_code,
                    "detail": err.detail,
                }
            )
            raise err from exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt < attempts - 1:
                logger.warning(
                    {
                        "event": "extract_fetch_retry",
                        "url_preview": url_preview(url),
                        "host": url_host(url),
                        "attempt": attempt + 1,
                        "reason": type(exc).__name__,
                    }
                )
                time.sleep(backoff * (attempt + 1))
                continue
            err = map_request_exception(exc)
            logger.error(
                {
                    "event": "extract_fetch_error",
                    "url_preview": url_preview(url),
                    "host": url_host(url),
                    "attempt": attempt + 1,
                    "status_code": err.status_code,
                    "detail": err.detail,
                }
            )
            raise err from exc
        except requests.RequestException as exc:
            err = map_request_exception(exc)
            logger.error(
                {
                    "event": "extract_fetch_error",
                    "url_preview": url_preview(url),
                    "host": url_host(url),
                    "attempt": attempt + 1,
                    "status_code": err.status_code,
                    "detail": err.detail,
                }
            )
            raise err from exc

    raise AssertionError("download_html: исчерпаны попытки без возврата или исключения")


# ======================
# PLAYWRIGHT
# ======================
def render_html_with_playwright(url: str) -> str:
    # "load" вместо "networkidle": меньше ложных таймаутов на SPA и сайтах с вечными запросами
    t0 = time.perf_counter()
    logger.info(
        {
            "event": "extract_playwright_request",
            "url_preview": url_preview(url),
            "host": url_host(url),
            "timeout_sec": settings.request_timeout,
        }
    )
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            try:
                page = browser.new_page(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="ru-RU",
                )

                page.goto(
                    url,
                    wait_until="load",
                    timeout=settings.request_timeout * 1000,
                )

                # Закрытие типовых cookie/CMP-баннеров, иначе trafilatura часто тянет текст оверлея
                settle_after_navigation(page, total_ms=3000)

                html = page.content()

                logger.info(
                    {
                        "event": "extract_playwright_success",
                        "url_preview": url_preview(url),
                        "host": url_host(url),
                        "duration_sec": round(time.perf_counter() - t0, 3),
                        "html_chars": len(html),
                    }
                )

                return html
            finally:
                browser.close()

    except PlaywrightTimeoutError as exc:
        raise http_exception_playwright_timeout() from exc
    except Exception as exc:
        raise http_exception_playwright_failed(exc) from exc


# ======================
# TRAFILATURA
# ======================
def extract_text_from_html(html: str, url: str | None = None) -> str | None:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

    if text:
        return text

    return trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
    )


# ======================
# BS4 FALLBACK
# ======================
def extract_text_with_bs4(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")

    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        tag.decompose()

    candidates = []

    for selector in [
        "article",
        "main",
        ".content",
        ".article",
        ".news",
        "body",
    ]:
        block = soup.select_one(selector)
        if block:
            text = block.get_text("\n", strip=True)
            if len(text) > 300:
                candidates.append(text)

    if not candidates:
        return None

    return max(candidates, key=len)


# ======================
# QUALITY
# ======================
def estimate_quality(text: str) -> tuple[str, bool]:
    length = len(text.strip())

    if length >= 2000:
        return "good", False

    if length >= 500:
        return "medium", True

    return "low", True


# ======================
# MAIN
# ======================
def extract_article_text(html: str, url: str | None = None) -> dict:
    t0 = time.perf_counter()
    logger.info(
        {
            "event": "extract_request",
            "url_preview": url_preview(url),
            "host": url_host(url),
            "html_chars": len(html),
            "has_url": bool(url),
        }
    )

    try:
        method = "requests+trafilatura"

        # 1. сначала чистим HTML
        html = shrink_html(html)

        # 2. пробуем trafilatura
        text = extract_text_from_html(html, url=url)

        # 3. fallback → playwright
        if not text and url:
            rendered_html = render_html_with_playwright(url)
            rendered_html = shrink_html(rendered_html)

            text = extract_text_from_html(rendered_html, url=url)
            html = rendered_html
            method = "playwright+trafilatura"

        # 4. fallback → bs4
        if not text:
            text = extract_text_with_bs4(html)
            method = "beautifulsoup"

        if not text:
            raise http_exception_extract_empty(had_url=bool(url))

        # ограничиваем текст (а не HTML!)
        if len(text) > 100_000:
            text = text[:100_000]

        metadata = trafilatura.extract_metadata(html)
        quality, needs_review = estimate_quality(text)

        images = extract_images(html, url) if url else []
        main_image = pick_main_image(images, html=html, base_url=url) if url else None

        result = {
            "title": metadata.title if metadata else None,
            "author": metadata.author if metadata else None,
            "date": metadata.date if metadata else None,
            "url": url,
            "text": text,
            "length": len(text),
            "method": method,
            "quality": quality,
            "needs_review": needs_review,
            "images": images,
            "main_image": main_image,
        }

        logger.info(
            {
                "event": "extract_success",
                "url_preview": url_preview(url),
                "host": url_host(url),
                "duration_sec": round(time.perf_counter() - t0, 3),
                "method": result["method"],
                "text_chars": result["length"],
                "quality": quality,
                "needs_review": needs_review,
                "html_chars_after_shrink": len(html),
                "images_count": len(images),
                "has_main_image": main_image is not None,
                "title_present": bool(metadata and metadata.title),
            }
        )

        return result

    except HTTPException as exc:
        logger.error(
            {
                "event": "extract_error",
                "url_preview": url_preview(url),
                "host": url_host(url),
                "duration_sec": round(time.perf_counter() - t0, 3),
                "status_code": exc.status_code,
                "detail": exc.detail,
            }
        )
        raise
