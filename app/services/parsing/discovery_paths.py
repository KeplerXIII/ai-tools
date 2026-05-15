from __future__ import annotations

from urllib.parse import urljoin, urlparse

from app.services.documents.url_norm import normalize_source_url

MAX_DISCOVERY_PATHS = 32
MAX_DISCOVERY_PATH_LEN = 512


def _discovery_path_key(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return normalize_source_url(path).lower()
    canonical = path if path.startswith("/") else f"/{path}"
    return canonical.lower()


def normalize_discovery_paths(paths: list[str] | None) -> list[str]:
    """Уникальные непустые пути от корня сайта (или полные URL)."""
    if not paths:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        p = raw.strip()
        if not p:
            continue
        if len(p) > MAX_DISCOVERY_PATH_LEN:
            p = p[:MAX_DISCOVERY_PATH_LEN]
        if not p.startswith("http://") and not p.startswith("https://") and not p.startswith("/"):
            p = f"/{p}"
        key = _discovery_path_key(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
        if len(out) >= MAX_DISCOVERY_PATHS:
            break
    return out


def build_discovery_page_urls(source_url: str, discovery_paths: list[str] | None) -> list[str]:
    """URL страниц для HTML-обхода по явным путям от origin сайта.

    Главная не обходится автоматически: для этого укажите ``/`` в ``discovery_paths``.
    Пустой список путей — HTML-листинги не скачиваются (остаётся только RSS, если задан).
    """
    parsed = urlparse(normalize_source_url(source_url))
    origin = f"{parsed.scheme}://{parsed.netloc}"

    pages: list[str] = []
    seen: set[str] = set()

    def add(url: str) -> None:
        normalized = normalize_source_url(url)
        if normalized not in seen:
            seen.add(normalized)
            pages.append(normalized)

    for raw in normalize_discovery_paths(discovery_paths):
        if raw.startswith("http://") or raw.startswith("https://"):
            add(raw)
            continue
        path = raw if raw.startswith("/") else f"/{raw}"
        if path == "/":
            add(f"{origin}/")
        else:
            add(urljoin(f"{origin}/", path.lstrip("/")))

    return pages
