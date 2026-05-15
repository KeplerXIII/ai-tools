"""Тесты путей HTML-обхода источника."""

from __future__ import annotations

import unittest

from app.services.parsing.discovery_paths import (
    build_discovery_page_urls,
    normalize_discovery_paths,
)


class DiscoveryPathsTests(unittest.TestCase):
    def test_normalize_dedupes_and_strips(self):
        self.assertEqual(
            normalize_discovery_paths([" /news ", "news", "", "/press"]),
            ["/news", "/press"],
        )

    def test_build_pages_from_origin_not_base_path(self):
        pages = build_discovery_page_urls(
            "https://www.army.mil",
            ["/news", "/news/newsreleases"],
        )
        self.assertEqual(
            pages,
            [
                "https://www.army.mil/",
                "https://www.army.mil/news",
                "https://www.army.mil/news/newsreleases",
            ],
        )

    def test_build_pages_only_base_when_paths_empty(self):
        pages = build_discovery_page_urls("https://example.com/", None)
        self.assertEqual(pages, ["https://example.com/"])

    def test_build_pages_accepts_full_url_path(self):
        pages = build_discovery_page_urls(
            "https://example.com",
            ["https://other.example/feed"],
        )
        self.assertEqual(
            pages,
            ["https://example.com/", "https://other.example/feed"],
        )

    def test_build_pages_path_without_leading_slash(self):
        pages = build_discovery_page_urls("https://example.com", ["news"])
        self.assertEqual(pages, ["https://example.com/", "https://example.com/news"])


if __name__ == "__main__":
    unittest.main()
