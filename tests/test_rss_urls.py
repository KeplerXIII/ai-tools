"""Тесты списка RSS-фидов источника."""

from __future__ import annotations

import unittest

from app.services.parsing.rss_urls import (
    legacy_rss_url_from_list,
    normalize_rss_urls,
    resolve_source_rss_urls,
    rss_urls_for_storage,
)


class RssUrlsTests(unittest.TestCase):
    def test_normalize_dedupes(self):
        self.assertEqual(
            normalize_rss_urls(
                [
                    " https://example.com/a.xml ",
                    "https://example.com/a.xml",
                    "https://example.com/b.xml",
                ],
            ),
            ["https://example.com/a.xml", "https://example.com/b.xml"],
        )

    def test_resolve_prefers_rss_urls(self):
        self.assertEqual(
            resolve_source_rss_urls(
                ["https://example.com/1.xml"],
                legacy_rss_url="https://example.com/old.xml",
            ),
            ["https://example.com/1.xml"],
        )

    def test_resolve_falls_back_to_legacy(self):
        self.assertEqual(
            resolve_source_rss_urls(None, legacy_rss_url="https://example.com/legacy.xml"),
            ["https://example.com/legacy.xml"],
        )

    def test_storage_empty_is_none(self):
        self.assertIsNone(rss_urls_for_storage([]))
        self.assertIsNone(legacy_rss_url_from_list([]))


if __name__ == "__main__":
    unittest.main()
