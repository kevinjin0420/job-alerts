from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.ashby import AshbySource


class AshbySourceFetchTests(unittest.TestCase):
    def _payload(self) -> bytes:
        return json.dumps(
            {
                "jobs": [
                    {
                        "id": "abc",
                        "title": "Software Engineer Intern",
                        "employmentType": "Intern",
                        "isListed": True,
                        "location": "Remote",
                        "jobUrl": "https://jobs.ashbyhq.com/example/abc",
                    },
                    {
                        "id": "def",
                        "title": "Senior Software Engineer",
                        "employmentType": "FullTime",
                        "isListed": True,
                        "location": "SF",
                        "jobUrl": "https://jobs.ashbyhq.com/example/def",
                    },
                    {
                        "id": "ghi",
                        "title": "Unlisted Intern Role",
                        "employmentType": "Intern",
                        "isListed": False,
                        "location": "Remote",
                        "jobUrl": "https://jobs.ashbyhq.com/example/ghi",
                    },
                ]
            }
        ).encode("utf-8")

    def test_filters_by_employment_type_and_listed_flag(self) -> None:
        source = AshbySource("Example", "example", "intern")
        with patch("sources.ashby.fetch_url", return_value=self._payload()):
            listings = source.fetch()

        self.assertEqual([listing.id for listing in listings], ["abc"])

    def test_newgrad_falls_back_to_fulltime(self) -> None:
        # Ashby has no distinct new-grad employment type - see EMPLOYMENT_TYPE_BY_JOB_TYPE.
        source = AshbySource("Example", "example", "newgrad")
        with patch("sources.ashby.fetch_url", return_value=self._payload()):
            listings = source.fetch()

        self.assertEqual([listing.id for listing in listings], ["def"])

    def test_name_uses_company_name_not_board_name(self) -> None:
        source = AshbySource("Example Co", "example-co-board", "intern")
        self.assertEqual(source.name, "ashby:Example Co:intern")


if __name__ == "__main__":
    unittest.main()
