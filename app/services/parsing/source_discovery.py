from __future__ import annotations

import email.utils
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from app.services.documents.url_norm import normalize_source_url
from app.services.parsing.extractor import download_html

MAX_DISCOVERED_LINKS = 400
NEWS_PATH_HINTS = ("/news", "/press", "/articles", "/media", "/blog")
ARTICLE_BLOCK_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".zip")


@dataclass
class DiscoveredUrl:
    url: str
    published_at: datetime | None


def _parse_any_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    parsed = email.utils.parsedate_to_datetime(text)
    if parsed is not None:
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _extract_date_from_url(url: str) -> datetime | None:
    patterns = (
        r"/(20\d{2})/(0[1-9]|1[0-2])/([0-2]\d|3[01])(?:/|$)",
        r"/(20\d{2})-(0[1-9]|1[0-2])-([0-2]\d|3[01])(?:/|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if not match:
            continue
        year, month, day = map(int, match.groups())
        try:
            return datetime(year, month, day, tzinfo=UTC)
        except ValueError:
            continue
    return None


def _is_article_like(base_host: str, href: str) -> bool:
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc and parsed.netloc != base_host:
        return False
    low = parsed.path.lower()
    if not low or low == "/":
        return False
    if low.endswith(ARTICLE_BLOCK_EXTENSIONS):
        return False
    if any(token in low for token in ("/tag/", "/category/", "/author/", "/search", "/login", "/signup")):
        return False
    if low.count("/") < 2:
        return False
    return True


def _extract_links_from_html(html: str, page_url: str, base_host: str) -> list[DiscoveredUrl]:
    soup = BeautifulSoup(html, "lxml")
    out: list[DiscoveredUrl] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        absolute = urljoin(page_url, href)
        normalized = normalize_source_url(absolute)
        if not _is_article_like(base_host, normalized):
            continue

        published_at: datetime | None = _extract_date_from_url(normalized)
        time_node = a.find_parent().find("time") if a.find_parent() else None
        if published_at is None and time_node is not None:
            published_at = _parse_any_date(
                time_node.get("datetime") or time_node.get_text(strip=True),
            )
        out.append(DiscoveredUrl(url=normalized, published_at=published_at))
    return out


def _within_days(published_at: datetime | None, threshold: datetime, *, skip_undated: bool) -> bool:
    if published_at is None:
        return not skip_undated
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    else:
        published_at = published_at.astimezone(UTC)
    return published_at >= threshold


def _first_text(node: ElementTree.Element, tags: tuple[str, ...]) -> str | None:
    for tag in tags:
        found = node.find(tag)
        if found is not None and found.text:
            return found.text.strip()
    return None


def _parse_rss_items(xml_text: str) -> list[DiscoveredUrl]:
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []

    items: list[DiscoveredUrl] = []
    # RSS 2.0
    for item in root.findall(".//item"):
        link = _first_text(item, ("link",))
        if not link:
            continue
        published = _parse_any_date(_first_text(item, ("pubDate", "date", "updated")))
        items.append(DiscoveredUrl(url=normalize_source_url(link), published_at=published))

    # Atom
    for entry in root.findall(".//{*}entry"):
        link = None
        for link_node in entry.findall("{*}link"):
            href = link_node.attrib.get("href")
            if href:
                link = href
                break
        if not link:
            continue
        published = _parse_any_date(_first_text(entry, ("{*}published", "{*}updated")))
        items.append(DiscoveredUrl(url=normalize_source_url(link), published_at=published))
    return items


async def discover_source_news_urls(
    source_url: str,
    *,
    rss_url: str | None,
    days: int,
    skip_undated: bool = True,
) -> list[DiscoveredUrl]:
    threshold = datetime.now(UTC) - timedelta(days=days)
    base = normalize_source_url(source_url)
    base_host = urlparse(base).netloc

    discovered: dict[str, DiscoveredUrl] = {}

    if rss_url:
        rss_xml = await download_html(rss_url)
        for item in _parse_rss_items(rss_xml):
            if _within_days(item.published_at, threshold, skip_undated=skip_undated):
                discovered[item.url] = item

    pages = [base]
    for suffix in NEWS_PATH_HINTS:
        pages.append(f"{base.rstrip('/')}{suffix}")

    for page_url in pages:
        try:
            html = await download_html(page_url)
        except Exception:
            continue
        for item in _extract_links_from_html(html, page_url, base_host):
            if _within_days(item.published_at, threshold, skip_undated=skip_undated):
                if item.url not in discovered:
                    discovered[item.url] = item
            if len(discovered) >= MAX_DISCOVERED_LINKS:
                break
        if len(discovered) >= MAX_DISCOVERED_LINKS:
            break

    return list(discovered.values())
