from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from classifier import ClassifierError
from sources.base import Listing
from watch import _job_type_url, build_job_type_sources, resolve_listing_validity


class BuildJobTypeSourcesZyteCooldownTests(unittest.TestCase):
    """Regression tests for build_job_type_sources' enforce_zyte_cooldown - see its docstring."""

    def setUp(self) -> None:
        self.catalog = {
            "meta": {
                "company_name": "Meta",
                "source_kind": "zyte",
                "intern_url": "https://www.metacareers.com/jobsearch/?roles[0]=Internship",
            }
        }
        self.pairs = {("Meta", "intern")}

    def test_cooldown_enforced_by_default_excludes_recently_succeeded_source(self) -> None:
        with patch("watch.get_source_last_success", return_value=time.time()):
            sources = build_job_type_sources(self.pairs, self.catalog)
        self.assertEqual(sources, [])

    def test_cooldown_disabled_includes_source_regardless_of_recency(self) -> None:
        with patch("watch.get_source_last_success", return_value=time.time()) as mock_get:
            sources = build_job_type_sources(self.pairs, self.catalog, enforce_zyte_cooldown=False)
        mock_get.assert_not_called()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "zyte:Meta:intern")

    def test_cooldown_enforced_still_includes_source_when_never_succeeded(self) -> None:
        with patch("watch.get_source_last_success", return_value=None):
            sources = build_job_type_sources(self.pairs, self.catalog)
        self.assertEqual(len(sources), 1)


class JobTypeUrlFallbackTests(unittest.TestCase):
    def test_uses_specific_url_when_present(self) -> None:
        entry = {"intern_url": "https://example.com/intern", "general_url": "https://example.com/all"}
        self.assertEqual(_job_type_url(entry, "intern"), "https://example.com/intern")

    def test_falls_back_to_general_url_when_specific_missing(self) -> None:
        entry = {"intern_url": "https://example.com/intern", "general_url": "https://example.com/all"}
        self.assertEqual(_job_type_url(entry, "newgrad"), "https://example.com/all")

    def test_returns_none_when_neither_is_set(self) -> None:
        entry = {"intern_url": "https://example.com/intern"}
        self.assertIsNone(_job_type_url(entry, "newgrad"))

    def test_tesla_style_entry_falls_back_for_newgrad_only(self) -> None:
        entry = {
            "intern_url": "https://www.tesla.com/careers/search/?type=intern",
            "fulltime_url": "https://www.tesla.com/careers/search/?type=fulltime",
            "general_url": "https://www.tesla.com/careers/search/",
        }
        self.assertEqual(_job_type_url(entry, "intern"), entry["intern_url"])
        self.assertEqual(_job_type_url(entry, "fulltime"), entry["fulltime_url"])
        self.assertEqual(_job_type_url(entry, "newgrad"), entry["general_url"])


def _listing(unique_source_id: str, company: str = "Example") -> Listing:
    return Listing(
        source="direct",
        id=unique_source_id,
        company_name=company,
        title=f"Intern {unique_source_id}",
        locations=["Remote"],
        url=f"https://example.com/jobs/{unique_source_id}",
    )


class ResolveListingValidityTests(unittest.TestCase):
    def test_cached_listings_skip_the_classifier_entirely(self) -> None:
        listing = _listing("1")
        with patch("watch.get_listing_validity", return_value={"is_job_posting": True, "reason": "cached"}):
            with patch("watch.check_is_job_posting") as mock_check:
                validity = resolve_listing_validity([listing], "fake-key", "fake-model")

        mock_check.assert_not_called()
        self.assertEqual(validity[listing.unique_id], (True, "cached"))

    def test_uncached_listings_are_checked_and_cached(self) -> None:
        listings = [_listing(str(i)) for i in range(5)]
        with patch("watch.get_listing_validity", return_value=None):
            with patch("watch.check_is_job_posting", return_value=(True, "looks real")) as mock_check:
                with patch("watch.save_listing_validity") as mock_save:
                    validity = resolve_listing_validity(listings, "fake-key", "fake-model")

        self.assertEqual(mock_check.call_count, 5)
        self.assertEqual(mock_save.call_count, 5)
        for listing in listings:
            self.assertEqual(validity[listing.unique_id], (True, "looks real"))

    def test_duplicate_unique_ids_are_only_checked_once(self) -> None:
        listing = _listing("1")
        with patch("watch.get_listing_validity", return_value=None):
            with patch("watch.check_is_job_posting", return_value=(True, "ok")) as mock_check:
                with patch("watch.save_listing_validity"):
                    resolve_listing_validity([listing, listing, listing], "fake-key", "fake-model")

        mock_check.assert_called_once()

    def test_classifier_error_assumes_valid(self) -> None:
        listing = _listing("1")
        with patch("watch.get_listing_validity", return_value=None):
            with patch("watch.check_is_job_posting", side_effect=ClassifierError("boom")):
                with patch("watch.save_listing_validity") as mock_save:
                    validity = resolve_listing_validity([listing], "fake-key", "fake-model")

        is_job_posting, reason = validity[listing.unique_id]
        self.assertTrue(is_job_posting)
        self.assertIn("boom", reason)
        mock_save.assert_called_once()

    def test_no_api_key_skips_everything(self) -> None:
        listing = _listing("1")
        with patch("watch.check_is_job_posting") as mock_check:
            validity = resolve_listing_validity([listing], None, "fake-model")

        mock_check.assert_not_called()
        self.assertEqual(validity, {})


if __name__ == "__main__":
    unittest.main()
