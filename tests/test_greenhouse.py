from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.greenhouse import GreenhouseSource


class GreenhouseSourceFetchTests(unittest.TestCase):
    def test_filters_to_internship_titles(self) -> None:
        payload = json.dumps(
            {
                "jobs": [
                    {
                        "id": 111,
                        "title": "Software Engineering Intern, Summer 2026",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://example.com/jobs/111",
                    },
                    {
                        "id": 222,
                        "title": "Senior Software Engineer",
                        "location": {"name": "SF"},
                        "absolute_url": "https://example.com/jobs/222",
                    },
                    {
                        "id": 333,
                        "title": "Internship - Data Science",
                        "location": {"name": "NYC"},
                        "absolute_url": "https://example.com/jobs/333",
                    },
                    # Missing id must be dropped even if the title matches.
                    {"title": "Marketing Intern", "location": {"name": "Remote"}, "absolute_url": ""},
                ]
            }
        ).encode("utf-8")

        source = GreenhouseSource("Example", "example")
        with patch("sources.greenhouse.fetch_url", return_value=payload):
            listings = source.fetch()

        self.assertEqual({listing.id for listing in listings}, {"111", "333"})
        self.assertEqual(listings[0].company_name, "Example")

    def test_name_uses_company_name_not_board_token(self) -> None:
        # Dashboard health-row matching relies on "{kind}:{company_name}:{job_type}" naming.
        source = GreenhouseSource("Example Co", "example-co-token")
        self.assertEqual(source.name, "greenhouse:Example Co:intern")


if __name__ == "__main__":
    unittest.main()
