from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch

from llm import LLMCallError
from sources.base import Listing

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
from classifier import ClassificationResult
from watch import (
    CLASSIFIER_HEALTH_KEY,
    SOURCE_FAILURE_ALERT_THRESHOLD,
    _ashby_job_type_tag,
    _job_type_url,
    _url_job_type_tag,
    build_job_type_sources,
    fetch_all_listings,
    passes_classifier,
    resolve_listing_validity,
)


class BuildJobTypeSourcesZyteCooldownTests(unittest.TestCase):
    """Regression tests for build_job_type_sources' enforce_fetch_cooldown - see its docstring."""

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
            sources = build_job_type_sources(self.pairs, self.catalog, enforce_fetch_cooldown=False)
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


class UrlJobTypeTagTests(unittest.TestCase):
    def test_shared_url_merges_into_one_tag(self) -> None:
        # Roblox's real config: intern_url and newgrad_url point at the same page.
        entry = {"intern_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
                  "newgrad_url": "https://careers.roblox.com/jobs?groups=early-career-talent"}
        self.assertEqual(_url_job_type_tag(entry, "intern"), "intern+newgrad")
        self.assertEqual(_url_job_type_tag(entry, "newgrad"), "intern+newgrad")

    def test_distinct_urls_stay_separate(self) -> None:
        entry = {"intern_url": "https://example.com/intern", "fulltime_url": "https://example.com/fulltime"}
        self.assertEqual(_url_job_type_tag(entry, "intern"), "intern")
        self.assertEqual(_url_job_type_tag(entry, "fulltime"), "fulltime")

    def test_tag_is_independent_of_which_job_types_a_caller_actually_wants(self) -> None:
        """A caller asking for only "intern" or only "newgrad" must resolve the same tag."""
        entry = {"intern_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
                  "newgrad_url": "https://careers.roblox.com/jobs?groups=early-career-talent"}
        self.assertEqual(_url_job_type_tag(entry, "intern"), _url_job_type_tag(entry, "newgrad"))


class AshbyJobTypeTagTests(unittest.TestCase):
    def test_newgrad_and_fulltime_merge(self) -> None:
        self.assertEqual(_ashby_job_type_tag("newgrad"), "fulltime+newgrad")
        self.assertEqual(_ashby_job_type_tag("fulltime"), "fulltime+newgrad")

    def test_intern_stays_separate(self) -> None:
        self.assertEqual(_ashby_job_type_tag("intern"), "intern")


class BuildJobTypeSourcesDedupTests(unittest.TestCase):
    def test_zyte_shared_url_across_job_types_produces_one_source(self) -> None:
        catalog = {
            "roblox": {
                "company_name": "Roblox",
                "source_kind": "zyte",
                "intern_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
                "newgrad_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
            }
        }
        pairs = {("Roblox", "intern"), ("Roblox", "newgrad")}
        sources = build_job_type_sources(pairs, catalog, enforce_fetch_cooldown=False)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "zyte:Roblox:intern+newgrad")

    def test_zyte_single_requested_job_type_still_resolves_merged_name(self) -> None:
        """A user who only configured "newgrad" must still resolve the shared fetch's merged name."""
        catalog = {
            "roblox": {
                "company_name": "Roblox",
                "source_kind": "zyte",
                "intern_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
                "newgrad_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
            }
        }
        sources = build_job_type_sources({("Roblox", "newgrad")}, catalog, enforce_fetch_cooldown=False)
        self.assertEqual(sources[0].name, "zyte:Roblox:intern+newgrad")

    def test_render_shared_url_across_job_types_produces_one_source(self) -> None:
        catalog = {
            "roblox": {
                "company_name": "Roblox",
                "source_kind": "renderer",
                "intern_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
                "newgrad_url": "https://careers.roblox.com/jobs?groups=early-career-talent",
            }
        }
        pairs = {("Roblox", "intern"), ("Roblox", "newgrad")}
        sources = build_job_type_sources(pairs, catalog, enforce_fetch_cooldown=False)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "renderer:Roblox:intern+newgrad")

    def test_ashby_newgrad_and_fulltime_produce_one_source(self) -> None:
        catalog = {"acme": {"company_name": "Acme", "source_kind": "ashby", "board_name": "acme"}}
        pairs = {("Acme", "newgrad"), ("Acme", "fulltime")}
        sources = build_job_type_sources(pairs, catalog)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].name, "ashby:Acme:fulltime+newgrad")

    def test_ashby_intern_stays_distinct_from_fulltime(self) -> None:
        catalog = {"acme": {"company_name": "Acme", "source_kind": "ashby", "board_name": "acme"}}
        pairs = {("Acme", "intern"), ("Acme", "fulltime")}
        sources = build_job_type_sources(pairs, catalog)
        names = sorted(source.name for source in sources)
        self.assertEqual(names, ["ashby:Acme:fulltime+newgrad", "ashby:Acme:intern"])


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
        with patch("watch.is_good_fit", side_effect=LLMCallError("429 too many requests")):
            with patch("watch.record_source_failure", return_value=1):
                result = passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        self.assertIsNone(result)

    def test_disabled_classifier_still_fails_open(self) -> None:
        result = passes_classifier(None, "fake-model", "must be remote", _listing("1"))
        self.assertEqual(result, ClassificationResult(fits=True, reason="classifier disabled"))

    def test_successful_call_passes_through_unchanged(self) -> None:
        expected = ClassificationResult(fits=False, reason="not remote")
        with patch("watch.is_good_fit", return_value=expected):
            with patch("watch.record_source_success") as mock_success:
                result = passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        self.assertEqual(result, expected)
        mock_success.assert_called_once_with(CLASSIFIER_HEALTH_KEY)


class ClassifierFailureAlertingTests(unittest.TestCase):
    """Persistent classifier failure should page admins once, not every run - same alerted-until-recovery pattern as source health."""

    def test_crossing_threshold_alerts_once(self) -> None:
        with patch("watch.is_good_fit", side_effect=LLMCallError("boom")):
            with patch("watch.record_source_failure", return_value=SOURCE_FAILURE_ALERT_THRESHOLD):
                with patch("watch.is_source_alerted", return_value=False):
                    with patch("watch.mark_source_alerted") as mock_mark:
                        with patch("watch.alert_admins_classifier_failing") as mock_alert:
                            passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        mock_mark.assert_called_once_with(CLASSIFIER_HEALTH_KEY)
        mock_alert.assert_called_once()

    def test_already_alerted_is_not_reported_again(self) -> None:
        with patch("watch.is_good_fit", side_effect=LLMCallError("boom")):
            with patch("watch.record_source_failure", return_value=SOURCE_FAILURE_ALERT_THRESHOLD):
                with patch("watch.is_source_alerted", return_value=True):
                    with patch("watch.mark_source_alerted") as mock_mark:
                        with patch("watch.alert_admins_classifier_failing") as mock_alert:
                            passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        mock_mark.assert_not_called()
        mock_alert.assert_not_called()

    def test_below_threshold_does_not_alert(self) -> None:
        with patch("watch.is_good_fit", side_effect=LLMCallError("boom")):
            with patch("watch.record_source_failure", return_value=1):
                with patch("watch.alert_admins_classifier_failing") as mock_alert:
                    passes_classifier("fake-key", "fake-model", "must be remote", _listing("1"))
        mock_alert.assert_not_called()


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

    def test_llm_error_assumes_valid(self) -> None:
        listing = _listing("1")
        with patch("watch.get_listing_validity", return_value=None):
            with patch("watch.check_is_job_posting", side_effect=LLMCallError("boom")):
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
