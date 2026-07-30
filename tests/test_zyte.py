from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.zyte import ZyteMisconfigured, ZyteSource, _extract_anchor_title


class ExtractAnchorTitleTests(unittest.TestCase):
    def test_flat_text_anchor(self) -> None:
        # The shape ZyteSource originally supported, before card-style SPAs.
        html = "Software Engineer Intern"
        self.assertEqual(_extract_anchor_title(html), "Software Engineer Intern")

    def test_nested_heading_anchor(self) -> None:
        # Meta-style: title lives in a heading buried under divs/spans, location/tags as later siblings.
        html = (
            '<div><div><h3 class="x1motxo8">Research Scientist Intern, AI/ML</h3></div></div>'
            '<div><span>Zurich, Switzerland</span><span>AI Research</span></div>'
        )
        self.assertEqual(_extract_anchor_title(html), "Research Scientist Intern, AI/ML")

    def test_decodes_html_entities(self) -> None:
        html = "<h3>FAIR - Language &amp; Multimodal Foundations</h3>"
        self.assertEqual(_extract_anchor_title(html), "FAIR - Language & Multimodal Foundations")

    def test_falls_back_to_full_text_without_heading(self) -> None:
        html = "<span>Data Engineer</span> <span>Intern</span>"
        self.assertEqual(_extract_anchor_title(html), "Data Engineer Intern")


def _mock_response(body: bytes) -> object:
    class _Response:
        status = 200

        def read(self) -> bytes:
            return body

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    return _Response()


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
            with patch("sources.zyte.urllib.request.urlopen", return_value=_mock_response(payload)):
                listings = source.fetch()

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].title, "Research Scientist Intern, AI/ML")
        self.assertEqual(listings[0].url, "https://www.metacareers.com/profile/job_details/771948392580541")


if __name__ == "__main__":
    unittest.main()
