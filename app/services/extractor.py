import requests
import trafilatura
from fastapi import HTTPException
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from app.core.config import settings
from app.services.image_extractor import extract_images, pick_main_image


BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


def download_html(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=settings.request_timeout,
            headers=BROWSER_HEADERS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка загрузки страницы: {exc}",
        )

    html = response.text

    if len(html) > settings.max_html_length:
        raise HTTPException(
            status_code=413,
            detail="HTML слишком большой для обработки",
        )

    return html


def render_html_with_playwright(url: str) -> str:
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

            page = browser.new_page(
                user_agent=BROWSER_HEADERS["User-Agent"],
                locale="ru-RU",
            )

            page.goto(
                url,
                wait_until="networkidle",
                timeout=settings.request_timeout * 1000,
            )

            page.wait_for_timeout(3000)

            html = page.content()
            browser.close()

            if len(html) > settings.max_html_length:
                raise HTTPException(
                    status_code=413,
                    detail="HTML после рендера слишком большой для обработки",
                )
            print("\n=== PLAYWRIGHT HTML DEBUG ===")
            print("LENGTH:", len(html))
            print("START:\n", html[:1000])
            print("END:\n", html[-1000:])
            print("=== END DEBUG ===\n")
            return html

    except PlaywrightTimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Таймаут рендера страницы через Playwright",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка Playwright при рендере страницы: {exc}",
        )


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


def estimate_quality(text: str) -> tuple[str, bool]:
    length = len(text.strip())

    if length >= 2000:
        return "good", False

    if length >= 500:
        return "medium", True

    return "low", True


def extract_article_text(html: str, url: str | None = None) -> dict:
    method = "requests+trafilatura"

    text = extract_text_from_html(html, url=url)

    if not text and url:
        rendered_html = render_html_with_playwright(url)
        text = extract_text_from_html(rendered_html, url=url)
        html = rendered_html
        method = "playwright+trafilatura"

    if not text:
        raise HTTPException(
            status_code=422,
            detail="Не удалось извлечь содержательный текст статьи",
        )

    metadata = trafilatura.extract_metadata(html)
    quality, needs_review = estimate_quality(text)

    images = extract_images(html, url) if url else []
    main_image = pick_main_image(images, html=html, base_url=url) if url else None

    return {
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