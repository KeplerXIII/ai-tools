from bs4 import BeautifulSoup
from urllib.parse import urljoin


BAD_IMAGE_MARKERS = [
    "logo",
    "icon",
    "sprite",
    "placeholder",
    "avatar",
    "teaser",
    "thumbnail",
]


def normalize_url(src: str | None, base_url: str) -> str | None:
    if not src:
        return None

    src = src.strip()

    if not src or src.startswith("data:"):
        return None

    return urljoin(base_url, src)


def extract_og_image(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")

    for selector in [
        ("property", "og:image"),
        ("property", "og:image:url"),
        ("name", "twitter:image"),
    ]:
        tag = soup.find("meta", attrs={selector[0]: selector[1]})
        if tag:
            image_url = normalize_url(tag.get("content"), base_url)
            if image_url:
                return image_url

    return None


def extract_images(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    images = []
    seen = set()

    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-original")
        )

        image_url = normalize_url(src, base_url)

        if not image_url or image_url in seen:
            continue

        seen.add(image_url)

        images.append({
            "url": image_url,
            "alt": img.get("alt"),
            "title": img.get("title"),
        })

    return images


def is_bad_image(image_url: str) -> bool:
    lower = image_url.lower()
    return any(marker in lower for marker in BAD_IMAGE_MARKERS)


def pick_main_image(images: list[dict], html: str | None = None, base_url: str | None = None) -> str | None:
    if html and base_url:
        og_image = extract_og_image(html, base_url)
        if og_image:
            return og_image

    if not images:
        return None

    filtered = [
        img for img in images
        if img.get("url") and not is_bad_image(img["url"])
    ]

    if not filtered:
        return None

    for img in filtered:
        alt = (img.get("alt") or "").lower()

        if any(word in alt for word in ["drohne", "munition", "loitering", "kamikaze"]):
            return img["url"]

    return filtered[0]["url"]