"""Нормализация URL для поиска дубликатов по documents.source_url."""

from urllib.parse import urldefrag, urlparse, urlunparse


def normalize_source_url(url: str) -> str:
    raw = url.strip()
    clean, _ = urldefrag(raw)
    p = urlparse(clean)
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    if not netloc and p.path:
        # URL без схемы вида //example.com/path
        p2 = urlparse(f"https:{clean}" if clean.startswith("//") else f"https://{clean}")
        scheme = "https"
        netloc = p2.netloc.lower()
        p = p2
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    query = p.query
    return urlunparse((scheme, netloc, path, "", query, ""))
