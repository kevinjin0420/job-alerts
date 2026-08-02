from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.greenhouse import GreenhouseSource


def _content_response(content: str | None) -> bytes:
    body: dict[str, object] = {} if content is None else {"content": content}
    return json.dumps(body).encode("utf-8")


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
        with patch(
            "sources.greenhouse.fetch_url",
            side_effect=[payload, _content_response(None), _content_response(None)],
        ):
            listings = source.fetch()

        self.assertEqual({listing.id for listing in listings}, {"111", "333"})
        self.assertEqual(listings[0].company_name, "Example")

    def test_content_true_not_on_the_list_url(self) -> None:
        # See _fetch_job_content's docstring - content=true on the list endpoint once
        # pulled full HTML for every job on the board (not just intern-titled ones) and
        # blew past the watch Lambda's memory limit on a large board.
        source = GreenhouseSource("Example", "example")
        with patch("sources.greenhouse.fetch_url", return_value=b'{"jobs": []}') as mock_fetch_url:
            source.fetch()

        requested_url = mock_fetch_url.call_args.args[1]
        self.assertNotIn("content=true", requested_url)
        self.assertEqual(requested_url, "https://boards-api.greenhouse.io/v1/boards/example/jobs")

    def test_description_is_fetched_per_job_and_stripped_of_html(self) -> None:
        list_payload = json.dumps(
            {
                "jobs": [
                    {
                        "id": 111,
                        "title": "Software Engineering Intern",
                        "location": {"name": "Remote"},
                        "absolute_url": "https://example.com/jobs/111",
                    }
                ]
            }
        ).encode("utf-8")
        source = GreenhouseSource("Example", "example")
        with patch(
            "sources.greenhouse.fetch_url",
            side_effect=[list_payload, _content_response("<p>Who we are.</p>")],
        ) as mock_fetch_url:
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Who we are.")
        content_url = mock_fetch_url.call_args_list[1].args[1]
        self.assertEqual(content_url, "https://boards-api.greenhouse.io/v1/boards/example/jobs/111?content=true")

    def test_missing_content_stays_none(self) -> None:
        list_payload = json.dumps(
            {"jobs": [{"id": 111, "title": "Intern", "location": {}, "absolute_url": "https://example.com/1"}]}
        ).encode("utf-8")
        source = GreenhouseSource("Example", "example")
        with patch("sources.greenhouse.fetch_url", side_effect=[list_payload, _content_response(None)]):
            listings = source.fetch()

        self.assertIsNone(listings[0].description)

    def test_content_fetch_failure_does_not_drop_the_listing(self) -> None:
        list_payload = json.dumps(
            {"jobs": [{"id": 111, "title": "Intern", "location": {}, "absolute_url": "https://example.com/1"}]}
        ).encode("utf-8")
        source = GreenhouseSource("Example", "example")
        with patch("sources.greenhouse.fetch_url", side_effect=[list_payload, RuntimeError("boom")]):
            listings = source.fetch()

        self.assertEqual(len(listings), 1)
        self.assertIsNone(listings[0].description)

    def test_name_uses_company_name_not_board_token(self) -> None:
        # Dashboard health-row matching relies on "{kind}:{company_name}:{job_type}" naming.
        source = GreenhouseSource("Example Co", "example-co-token")
        self.assertEqual(source.name, "greenhouse:Example Co:intern")


if __name__ == "__main__":
    unittest.main()
