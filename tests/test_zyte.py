from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.base import RENDERED_DESCRIPTION_MAX_CHARS
from sources.zyte import ZyteMisconfigured, ZyteSource, fetch_zyte_description


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


class FetchZyteDescriptionTests(unittest.TestCase):
    def test_strips_html_from_rendered_page(self) -> None:
        payload = json.dumps({"browserHtml": "<nav>Meta</nav><main><p>Great role.</p></main>"}).encode("utf-8")
        with patch.dict("os.environ", {"ZYTE_API_KEY": "fake-key"}):
            with patch("sources.zyte.fetch_url", return_value=payload):
                description = fetch_zyte_description("https://www.metacareers.com/job/1")

        self.assertEqual(description, "Meta Great role.")

    def test_truncates_very_long_pages(self) -> None:
        payload = json.dumps({"browserHtml": f"<p>{'x' * (RENDERED_DESCRIPTION_MAX_CHARS + 500)}</p>"}).encode("utf-8")
        with patch.dict("os.environ", {"ZYTE_API_KEY": "fake-key"}):
            with patch("sources.zyte.fetch_url", return_value=payload):
                description = fetch_zyte_description("https://www.metacareers.com/job/1")

        assert description is not None
        self.assertEqual(len(description), RENDERED_DESCRIPTION_MAX_CHARS)

    def test_missing_api_key_returns_none_instead_of_raising(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(fetch_zyte_description("https://www.metacareers.com/job/1"))

    def test_fetch_failure_returns_none_instead_of_raising(self) -> None:
        with patch.dict("os.environ", {"ZYTE_API_KEY": "fake-key"}):
            with patch("sources.zyte.fetch_url", side_effect=RuntimeError("boom")):
                self.assertIsNone(fetch_zyte_description("https://www.metacareers.com/job/1"))


if __name__ == "__main__":
    unittest.main()
