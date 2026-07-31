from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from classifier import ClassificationResult, ClassifierError
from sources.base import Listing
from watch import (
    SOURCE_FAILURE_ALERT_THRESHOLD,
    _job_type_url,
    build_job_type_sources,
    fetch_all_listings,
    passes_classifier,
    resolve_listing_validity,
)


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


class PassesClassifierFailureModeTests(unittest.TestCase):
    """Regression tests for the "friend getting spammed" incident: a classifier
    failure must never fail open with fits=True anymore - see passes_classifier's
    docstring. None means "retry next run", not "notify"."""

    def test_returns_none_on_classifier_error_instead_of_notifying(self) -> None:
        with patch("watch.is_good_fit", side_effect=ClassifierError("429 too many requests")):
            result = passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        self.assertIsNone(result)

    def test_disabled_classifier_still_fails_open(self) -> None:
        result = passes_classifier(None, "fake-model", "must be remote", _listing("1"))
        self.assertEqual(result, ClassificationResult(fits=True, reason="classifier disabled"))

    def test_successful_call_passes_through_unchanged(self) -> None:
        expected = ClassificationResult(fits=False, reason="not remote")
        with patch("watch.is_good_fit", return_value=expected):
            result = passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        self.assertEqual(result, expected)


class _FakeSource:
    def __init__(self, name: str, listings: list[Listing] | None = None, error: Exception | None = None) -> None:
        self.name = name
        self._listings = listings or []
        self._error = error

    def fetch(self) -> list[Listing]:
        if self._error is not None:
            raise self._error
        return self._listings


class FetchAllListingsConcurrencyTests(unittest.TestCase):
    """Sequential fetching was measured at 47s+ of pure network time across ~46 sources; now parallelized."""

    def test_fetches_all_sources_and_aggregates_listings(self) -> None:
        sources = [
            _FakeSource("a", [_listing("1")]),
            _FakeSource("b", [_listing("2"), _listing("3")]),
        ]
        with patch("watch.record_source_success"):
            listings, unhealthy = fetch_all_listings(sources)

        self.assertEqual(len(listings), 3)
        self.assertEqual(unhealthy, [])

    def test_one_source_failing_does_not_block_others(self) -> None:
        sources = [_FakeSource("good", [_listing("1")]), _FakeSource("bad", error=RuntimeError("boom"))]
        with patch("watch.record_source_success"):
            with patch("watch.record_source_failure", return_value=1):
                with patch("watch.is_source_alerted", return_value=False):
                    listings, unhealthy = fetch_all_listings(sources)

        self.assertEqual(len(listings), 1)
        self.assertEqual(unhealthy, [])

    def test_source_crossing_failure_threshold_is_reported_once(self) -> None:
        sources = [_FakeSource("bad", error=RuntimeError("boom"))]
        with patch("watch.record_source_failure", return_value=SOURCE_FAILURE_ALERT_THRESHOLD):
            with patch("watch.is_source_alerted", return_value=False):
                with patch("watch.mark_source_alerted") as mock_mark:
                    listings, unhealthy = fetch_all_listings(sources)

        self.assertEqual(unhealthy, ["bad"])
        mock_mark.assert_called_once_with("bad")

    def test_already_alerted_source_is_not_reported_again(self) -> None:
        sources = [_FakeSource("bad", error=RuntimeError("boom"))]
        with patch("watch.record_source_failure", return_value=SOURCE_FAILURE_ALERT_THRESHOLD):
            with patch("watch.is_source_alerted", return_value=True):
                with patch("watch.mark_source_alerted") as mock_mark:
                    listings, unhealthy = fetch_all_listings(sources)

        self.assertEqual(unhealthy, [])
        mock_mark.assert_not_called()


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
