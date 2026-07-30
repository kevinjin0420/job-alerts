from __future__ import annotations

import unittest
from unittest.mock import patch

from sources.direct import DirectSource


class DirectSourceFetchTests(unittest.TestCase):
    def test_parses_markdown_links_and_filters_noise(self) -> None:
        markdown = (
            "[Skip to content](https://example.com/careers#main)\n"
            "[Software Engineer Intern](https://example.com/positions/48213/)\n"
            "[Home](https://example.com/)\n"
            # Duplicate link should be deduped.
            "[Software Engineer Intern](https://example.com/positions/48213/)\n"
            "[Data Engineer Intern](https://example.com/positions/48219/)\n"
        )
        source = DirectSource("Example", "https://example.com/careers?type=intern", "intern")
        with patch("sources.direct.fetch_url", return_value=markdown.encode("utf-8")):
            listings = source.fetch()

        self.assertEqual(len(listings), 2)
        titles = {listing.title for listing in listings}
        self.assertEqual(titles, {"Software Engineer Intern", "Data Engineer Intern"})

    def test_skips_short_titles(self) -> None:
        markdown = "[Go](https://example.com/positions/48213/)\n"
        source = DirectSource("Example", "https://example.com/careers?type=intern", "intern")
        with patch("sources.direct.fetch_url", return_value=markdown.encode("utf-8")):
            listings = source.fetch()

        self.assertEqual(listings, [])


if __name__ == "__main__":
    unittest.main()
