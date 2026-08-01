from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.zyte import ZyteMisconfigured, ZyteSource


class ZyteSourceFetchTests(unittest.TestCase):
    def test_raises_when_api_key_missing(self) -> None:
        source = ZyteSource("Example", "https://example.com/careers", "intern")
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ZyteMisconfigured):
                source.fetch()

    def test_parses_card_style_listings_and_dedupes(self) -> None:
        browser_html = (
            '<a href="/profile/job_details/771948392580541">'
            '<div><h3>Research Scientist Intern, AI/ML</h3></div>'
            '<span>Zurich, Switzerland</span></a>'
            # A repeat of the same href (e.g. a duplicate mobile/desktop card) must be deduped.
            '<a href="/profile/job_details/771948392580541"><h3>Research Scientist Intern, AI/ML</h3></a>'
            # Nav/footer-style link with no numeric id must be dropped.
            '<a href="/about">About Meta</a>'
        )
        payload = json.dumps({"browserHtml": browser_html}).encode("utf-8")

        source = ZyteSource("Meta", "https://www.metacareers.com/jobsearch/?roles[0]=Internship", "intern")
        with patch.dict("os.environ", {"ZYTE_API_KEY": "fake-key"}):
            with patch("sources.zyte.fetch_url", return_value=payload):
                listings = source.fetch()

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Research Scientist Intern, AI/ML")
        self.assertEqual(listings[0].url, "https://www.metacareers.com/profile/job_details/771948392580541")


if __name__ == "__main__":
    unittest.main()
