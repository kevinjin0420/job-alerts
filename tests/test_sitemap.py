from __future__ import annotations

import unittest
from unittest.mock import patch

from sources.sitemap import SitemapSource

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/careers/software-engineer-intern_1affb074-f055-4f5a-a97e-80d97d77da6e</loc></url>
<url><loc>https://example.com/careers/staff-software-engineer-internal-tools_62d779d3-51c8-4b0a-ab2e-1a440276bb37</loc></url>
<url><loc>https://example.com/careers/senior-account-executive_9f16f862-28ec-42d7-a9fa-948bf2eeeb4a</loc></url>
</urlset>
"""


def _mock_response(body: str) -> bytes:
    return body.encode("utf-8")


class SitemapSourceFetchTests(unittest.TestCase):
    def test_filters_to_internship_slugs_and_humanizes_title(self) -> None:
        source = SitemapSource("Example", "https://example.com/careers/sitemap.xml")
        with patch("sources.sitemap.fetch_url", return_value=_mock_response(SAMPLE_XML)):
            listings = source.fetch()

        # "internal-tools" must not false-positive-match "intern" (INTERNSHIP_TITLE_PATTERN uses a word boundary).
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Software Engineer Intern")
        self.assertEqual(
            listings[0].url,
            "https://example.com/careers/software-engineer-intern_1affb074-f055-4f5a-a97e-80d97d77da6e",
        )

    def test_name_uses_company_name(self) -> None:
        source = SitemapSource("Example", "https://example.com/careers/sitemap.xml")
        self.assertEqual(source.name, "sitemap:Example:intern")


if __name__ == "__main__":
    unittest.main()
