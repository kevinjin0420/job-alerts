from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.workday import WorkdaySource


def _mock_response(body: dict[str, object]) -> bytes:
    return json.dumps(body).encode("utf-8")


FACETS_RESPONSE = {
    "total": 2,
    "jobPostings": [],
    "facets": [
        {
            "facetParameter": "workerSubType",
            "descriptor": "Job Type",
            "values": [
                {"descriptor": "Regular Employee", "id": "reg-id", "count": 900},
                {"descriptor": "New College Graduate", "id": "newgrad-id", "count": 40},
                {"descriptor": "Intern (Fixed Term)", "id": "intern-id", "count": 2},
            ],
        }
    ],
}


class WorkdaySourceFetchTests(unittest.TestCase):
    def test_fetches_single_page_of_matching_job_type(self) -> None:
        page_response = {
            "total": 2,
            "jobPostings": [
                {
                    "title": "Software Engineering Intern",
                    "externalPath": "/job/US-CA-Santa-Clara/Software-Engineering-Intern_JR001",
                    "locationsText": "US, CA, Santa Clara",
                    "bulletFields": ["JR001"],
                },
                {
                    "title": "Data Science Intern",
                    "externalPath": "/job/US-Remote/Data-Science-Intern_JR002",
                    "locationsText": "US, Remote",
                    "bulletFields": ["JR002"],
                },
            ],
        }
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "intern")
        with patch(
            "sources.workday.fetch_url",
            side_effect=[_mock_response(FACETS_RESPONSE), _mock_response(page_response)],
        ):
            listings = source.fetch()

        self.assertEqual(len(listings), 2)
        self.assertEqual(listings[0].title, "Software Engineering Intern")
        self.assertEqual(listings[0].id, "JR001")
        self.assertEqual(
            listings[0].url,
            "https://example.wd5.myworkdayjobs.com/ExampleCareerSite/job/US-CA-Santa-Clara/Software-Engineering-Intern_JR001",
        )

    def test_newgrad_matches_new_college_graduate_descriptor(self) -> None:
        page_response = {"total": 0, "jobPostings": []}
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "newgrad")
        with patch(
            "sources.workday.fetch_url",
            side_effect=[_mock_response(FACETS_RESPONSE), _mock_response(page_response)],
        ) as mock_fetch_url:
            source.fetch()

        second_call_body = json.loads(mock_fetch_url.call_args_list[1].kwargs["data"])
        self.assertEqual(second_call_body["appliedFacets"], {"workerSubType": ["newgrad-id"]})

    def test_paginates_past_first_page(self) -> None:
        # Workday reports "total" accurately only on the first page (0 on every later page).
        full_page = {
            "total": 25,
            "jobPostings": [
                {
                    "title": f"Intern {i}",
                    "externalPath": f"/job/Remote/Intern-{i}_JR{i:03d}",
                    "locationsText": "Remote",
                    "bulletFields": [f"JR{i:03d}"],
                }
                for i in range(20)
            ],
        }
        last_page = {
            "total": 0,
            "jobPostings": [
                {
                    "title": f"Intern {i}",
                    "externalPath": f"/job/Remote/Intern-{i}_JR{i:03d}",
                    "locationsText": "Remote",
                    "bulletFields": [f"JR{i:03d}"],
                }
                for i in range(20, 25)
            ],
        }
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "intern")
        with patch(
            "sources.workday.fetch_url",
            side_effect=[_mock_response(FACETS_RESPONSE), _mock_response(full_page), _mock_response(last_page)],
        ):
            listings = source.fetch()

        self.assertEqual(len(listings), 25)

    def test_fulltime_matches_bare_regular_descriptor(self) -> None:
        # Some tenants (e.g. Adobe) label the facet "Regular" rather than "Regular Employee".
        bare_regular_facets = {
            "total": 0,
            "jobPostings": [],
            "facets": [
                {
                    "facetParameter": "workerSubType",
                    "descriptor": "Job Type",
                    "values": [
                        {"descriptor": "Regular", "id": "bare-regular-id", "count": 835},
                        {"descriptor": "Intern (Fixed Term)", "id": "intern-id", "count": 3},
                    ],
                }
            ],
        }
        page_response = {"total": 0, "jobPostings": []}
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "fulltime")
        with patch(
            "sources.workday.fetch_url",
            side_effect=[_mock_response(bare_regular_facets), _mock_response(page_response)],
        ) as mock_fetch_url:
            source.fetch()

        second_call_body = json.loads(mock_fetch_url.call_args_list[1].kwargs["data"])
        self.assertEqual(second_call_body["appliedFacets"], {"workerSubType": ["bare-regular-id"]})

    def test_intern_falls_back_to_job_family_group_when_no_worker_sub_type_facet(self) -> None:
        # Some tenants (e.g. Workday's own site) expose no workerSubType facet at all - a "University" jobFamilyGroup is the only early-career signal.
        university_only_facets = {
            "total": 0,
            "jobPostings": [],
            "facets": [
                {
                    "facetParameter": "jobFamilyGroup",
                    "descriptor": "Job Category",
                    "values": [
                        {"descriptor": "Product Development and Engineering", "id": "eng-id", "count": 103},
                        {"descriptor": "University", "id": "university-id", "count": 1},
                    ],
                }
            ],
        }
        page_response = {"total": 0, "jobPostings": []}
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "intern")
        with patch(
            "sources.workday.fetch_url",
            side_effect=[_mock_response(university_only_facets), _mock_response(page_response)],
        ) as mock_fetch_url:
            source.fetch()

        second_call_body = json.loads(mock_fetch_url.call_args_list[1].kwargs["data"])
        self.assertEqual(second_call_body["appliedFacets"], {"jobFamilyGroup": ["university-id"]})

    def test_returns_empty_when_no_matching_worker_sub_type(self) -> None:
        source = WorkdaySource("Example", "wd5", "example", "ExampleCareerSite", "intern")
        no_intern_facets = {
            "total": 0,
            "jobPostings": [],
            "facets": [
                {
                    "facetParameter": "workerSubType",
                    "descriptor": "Job Type",
                    "values": [{"descriptor": "Regular Employee", "id": "reg-id", "count": 900}],
                }
            ],
        }
        with patch("sources.workday.fetch_url", return_value=_mock_response(no_intern_facets)):
            listings = source.fetch()

        self.assertEqual(listings, [])

    def test_name_uses_company_name_not_tenant(self) -> None:
        source = WorkdaySource("Example Co", "wd5", "example-co-tenant", "ExampleCareerSite", "intern")
        self.assertEqual(source.name, "workday:Example Co:intern")


if __name__ == "__main__":
    unittest.main()
