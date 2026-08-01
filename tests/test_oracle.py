from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.oracle import OracleSource


def _mock_response(requisitions: list[dict[str, object]]) -> bytes:
    return json.dumps({"items": [{"requisitionList": requisitions}]}).encode("utf-8")


class OracleSourceFetchTests(unittest.TestCase):
    def test_filters_noisy_keyword_search_by_title(self) -> None:
        requisitions = [
            {"Id": "1", "Title": "Software Engineering Intern", "PrimaryLocation": "Austin, TX"},
            {"Id": "2", "Title": "Senior Internal Auditor", "PrimaryLocation": "Chicago, IL"},
            {"Id": "3", "Title": "Marketing Internship"},
        ]
        source = OracleSource("Oracle")
        with patch("sources.oracle.fetch_url", side_effect=[_mock_response(requisitions), _mock_response([])]):
            listings = source.fetch()

        self.assertEqual({listing.id for listing in listings}, {"1", "3"})
        self.assertEqual(
            next(l.url for l in listings if l.id == "1"),
            "https://careers.oracle.com/jobs/#en/sites/jobsearch/job/1",
        )

    def test_dedupes_across_pages(self) -> None:
        page = [{"Id": "1", "Title": "Software Intern", "PrimaryLocation": "Remote"}]
        source = OracleSource("Oracle")
        with patch("sources.oracle.fetch_url", side_effect=[_mock_response(page), _mock_response(page), _mock_response([])]):
            listings = source.fetch()

        # Real pagination stops once a page returns nothing, but a duplicate id
        # showing up again mid-pagination (e.g. a shifting relevancy sort) must
        # still not produce a second listing.
        self.assertEqual(len(listings), 1)

    def test_name_uses_company_name(self) -> None:
        source = OracleSource("Oracle")
        self.assertEqual(source.name, "oracle:Oracle:intern")


if __name__ == "__main__":
    unittest.main()
