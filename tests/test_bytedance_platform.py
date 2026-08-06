from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sources.bytedance_platform import ByteDancePlatformJobsSource, bytedance_platform_source


def _mock_response(count: int, posts: list[dict[str, object]]) -> bytes:
    return json.dumps({"code": 0, "data": {"job_post_list": posts, "count": count}}).encode("utf-8")


def _post(post_id: str = "1", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": post_id,
        "title": "Software Engineer Intern",
        "description": " Build things. ",
        "city_info": {
            "en_name": "San Jose",
            "parent": {"en_name": "California", "parent": {"en_name": "United States of America", "parent": None}},
        },
    }
    base.update(overrides)
    return base


class ByteDancePlatformJobsSourceFetchTests(unittest.TestCase):
    def _source(self, job_type: str = "intern") -> ByteDancePlatformJobsSource:
        return ByteDancePlatformJobsSource(
            "Acme",
            job_type,
            source_kind="acme",
            api_url="https://api.example.com/search",
            detail_url_prefix="https://example.com/jobs/",
            headers={"Content-Type": "application/json"},
        )

    def test_parses_posts(self) -> None:
        source = self._source()
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [_post("123")])):
            listings = source.fetch()

        self.assertEqual(len(listings), 1)
        listing = listings[0]
        self.assertEqual(listing.id, "123")
        self.assertEqual(listing.title, "Software Engineer Intern")
        self.assertEqual(listing.url, "https://example.com/jobs/123")
        self.assertEqual(listing.locations, ["San Jose", "United States of America"])
        self.assertEqual(listing.description, "Build things.")

    def test_missing_description_stays_none(self) -> None:
        source = self._source()
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [_post(description="")])):
            listings = source.fetch()

        self.assertIsNone(listings[0].description)

    def test_requirement_merged_into_description(self) -> None:
        source = self._source()
        post = _post(description="Build things.", requirement="Available Summer of 2027.")
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [post])):
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Build things.\n\nAvailable Summer of 2027.")

    def test_missing_description_falls_back_to_requirement_only(self) -> None:
        source = self._source()
        post = _post(description="", requirement="Available Summer of 2027.")
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [post])):
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Available Summer of 2027.")

    def test_job_subject_leads_description_with_intake_year(self) -> None:
        source = self._source()
        post = _post(
            description="Build things.",
            requirement="Strong CS fundamentals.",
            job_subject={"en_name": "Undergraduate/Master Intern - 2027 Start"},
        )
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [post])):
            listings = source.fetch()

        self.assertEqual(
            listings[0].description,
            "Program: Undergraduate/Master Intern - 2027 Start\n\nBuild things.\n\nStrong CS fundamentals.",
        )

    def test_missing_job_subject_leaves_description_unchanged(self) -> None:
        source = self._source()
        post = _post(description="Build things.", job_subject=None)
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [post])):
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Build things.")

    def test_job_subject_alone_still_reaches_the_classifier(self) -> None:
        source = self._source()
        post = _post(description="", job_subject={"en_name": "PhD Intern - 2027 Start"})
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [post])):
            listings = source.fetch()

        self.assertEqual(listings[0].description, "Program: PhD Intern - 2027 Start")

    def test_missing_city_info_yields_no_locations(self) -> None:
        source = self._source()
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(1, [_post(city_info=None)])):
            listings = source.fetch()

        self.assertEqual(listings[0].locations, [])

    def test_paginates_until_count_is_reached(self) -> None:
        source = self._source()
        full_page = [_post(str(i)) for i in range(50)]
        page1 = _mock_response(51, full_page)
        page2 = _mock_response(51, [_post("50")])
        with patch("sources.bytedance_platform.fetch_url", side_effect=[page1, page2]) as mock_fetch:
            listings = source.fetch()

        self.assertEqual(mock_fetch.call_count, 2)
        self.assertEqual(len(listings), 51)
        self.assertEqual(listings[-1].id, "50")

    def test_short_page_stops_pagination_even_below_count(self) -> None:
        source = self._source()
        short_page = _mock_response(500, [_post("1")])
        with patch("sources.bytedance_platform.fetch_url", return_value=short_page) as mock_fetch:
            listings = source.fetch()

        mock_fetch.assert_called_once()
        self.assertEqual(len(listings), 1)

    def test_request_body_includes_category_and_program_filters(self) -> None:
        source = self._source("newgrad")
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(0, [])) as mock_fetch:
            source.fetch()

        body = json.loads(mock_fetch.call_args.kwargs["data"])
        self.assertEqual(body["recruitment_id_list"], ["201"])
        self.assertEqual(body["job_category_id_list"], ["6704215862603155720"])
        self.assertEqual(len(body["subject_id_list"]), 6)

    def test_returns_empty_for_unsupported_job_type(self) -> None:
        source = self._source("fulltime")
        with patch("sources.bytedance_platform.fetch_url") as mock_fetch:
            listings = source.fetch()

        mock_fetch.assert_not_called()
        self.assertEqual(listings, [])


class SiteFactoryTests(unittest.TestCase):
    """Every brand on this shared platform reports as "bytedance:{company}:{job_type}" -
    that's who owns the site, not which fetch mechanism is used - dispatch picks the right
    host/headers per company name under the hood (see _SITE_CONFIG_BY_COMPANY_NAME)."""

    def test_tiktok_source_reports_as_bytedance_but_targets_lifeattiktok(self) -> None:
        source = bytedance_platform_source("TikTok", "intern")
        assert source is not None
        self.assertEqual(source.name, "bytedance:TikTok:intern")
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(0, [])) as mock_fetch:
            source.fetch()

        self.assertEqual(mock_fetch.call_args.args[1], "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts")
        self.assertEqual(mock_fetch.call_args.kwargs["headers"]["website-path"], "tiktok")

    def test_bytedance_source_reports_as_bytedance_and_targets_jobs_bytedance(self) -> None:
        source = bytedance_platform_source("ByteDance", "intern")
        assert source is not None
        self.assertEqual(source.name, "bytedance:ByteDance:intern")
        with patch("sources.bytedance_platform.fetch_url", return_value=_mock_response(0, [])) as mock_fetch:
            source.fetch()

        self.assertEqual(mock_fetch.call_args.args[1], "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts")
        self.assertEqual(mock_fetch.call_args.kwargs["headers"]["website-path"], "en")
        self.assertEqual(mock_fetch.call_args.kwargs["headers"]["x-tt-env"], "boe_epam_api")

    def test_unknown_company_returns_none(self) -> None:
        self.assertIsNone(bytedance_platform_source("SomeOtherCompany", "intern"))

    def test_company_name_lookup_is_case_insensitive(self) -> None:
        source = bytedance_platform_source("TIKTOK", "intern")
        assert source is not None
        self.assertEqual(source.name, "bytedance:TIKTOK:intern")


if __name__ == "__main__":
    unittest.main()
