import requests
import trafilatura
from fastapi import HTTPException

from app.core.config import settings
from app.services.image_extractor import extract_images, pick_main_image


def download_html(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=settings.request_timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 AI-Tools/0.1 "
                    "(compatible; article-extractor)"
                )
            },
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


def estimate_quality(text: str) -> tuple[str, bool]:
    length = len(text.strip())

    if length >= 2000:
        return "good", False

    if length >= 500:
        return "medium", True

    return "low", True


def extract_article_text(html: str, url: str | None = None) -> dict:
    text = trafilatura.extract(
        html,
        url=url,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )

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
        "method": "trafilatura",
        "quality": quality,
        "needs_review": needs_review,
        "images": images,
        "main_image": main_image,
    }