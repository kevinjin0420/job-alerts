from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.amazon import AmazonJobsSource


def _mock_response(body: dict[str, object]) -> bytes:
    return json.dumps(body).encode("utf-8")


class AmazonJobsSourceFetchTests(unittest.TestCase):
    def test_parses_jobs(self) -> None:
        payload = {
            "jobs": [
                {
                    "id_icims": "3083050",
                    "job_path": "/en/jobs/3083050/engineering-intern",
                    "title": "Engineering Intern",
                    "normalized_location": "Agognate, Italy",
                },
                # Missing job_path must be dropped.
                {"id_icims": "999", "job_path": "", "title": "Broken Entry"},
            ]
        }
        source = AmazonJobsSource("Amazon", "intern")
        with patch("sources.amazon.fetch_url", return_value=_mock_response(payload)):
            listings = source.fetch()

        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].id, "3083050")
        self.assertEqual(listings[0].url, "https://www.amazon.jobs/en/jobs/3083050/engineering-intern")
        self.assertEqual(listings[0].locations, ["Agognate, Italy"])

    def test_description_is_extracted_and_stripped_of_html(self) -> None:
        payload = {
            "jobs": [
                {
                    "id_icims": "3083050",
                    "job_path": "/en/jobs/3083050/engineering-intern",
                    "title": "Engineering Intern",
                    "description": "<p>Build things at</p><p>Amazon.</p>",
                }
            ]
        }
        source = AmazonJobsSource("Amazon", "intern")
        with patch("sources.amazon.fetch_url", return_value=_mock_response(payload)):
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Build things at Amazon.")

    def test_missing_description_stays_none(self) -> None:
        payload = {"jobs": [{"id_icims": "3083050", "job_path": "/en/jobs/3083050/x", "title": "x"}]}
        source = AmazonJobsSource("Amazon", "intern")
        with patch("sources.amazon.fetch_url", return_value=_mock_response(payload)):
            listings = source.fetch()

        self.assertIsNone(listings[0].description)

    def test_returns_empty_for_unsupported_job_type(self) -> None:
        source = AmazonJobsSource("Amazon", "fulltime")
        with patch("sources.amazon.fetch_url") as mock_fetch_url:
            listings = source.fetch()

        mock_fetch_url.assert_not_called()
        self.assertEqual(listings, [])

    def test_name_includes_company_name(self) -> None:
        source = AmazonJobsSource("Amazon", "intern")
        self.assertEqual(source.name, "amazon:Amazon:intern")


if __name__ == "__main__":
    unittest.main()
