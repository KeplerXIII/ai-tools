from __future__ import annotations

from app.services.documents.url_norm import normalize_source_url

MAX_RSS_URLS = 16
MAX_RSS_URL_LEN = 2048


def normalize_rss_urls(urls: list[str] | None) -> list[str]:
    """Уникальные нормализованные URL RSS/Atom-фидов."""
    if not urls:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        u = raw.strip()
        if not u:
            continue
        if len(u) > MAX_RSS_URL_LEN:
            u = u[:MAX_RSS_URL_LEN]
        if not u.startswith("http://") and not u.startswith("https://"):
            continue
        normalized = normalize_source_url(u)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
        if len(out) >= MAX_RSS_URLS:
            break
    return out


def resolve_source_rss_urls(
    rss_urls: list[str] | None,
    *,
    legacy_rss_url: str | None = None,
) -> list[str]:
    """Список фидов из ``rss_urls`` или устаревшего одиночного ``rss_url``."""
    urls = normalize_rss_urls(rss_urls)
    if urls:
        return urls
    if legacy_rss_url:
        return normalize_rss_urls([legacy_rss_url])
    return []


def rss_urls_for_storage(urls: list[str] | None) -> list[str] | None:
    normalized = normalize_rss_urls(urls)
    return normalized or None


def legacy_rss_url_from_list(urls: list[str] | None) -> str | None:
    normalized = normalize_rss_urls(urls)
    return normalized[0] if normalized else None
