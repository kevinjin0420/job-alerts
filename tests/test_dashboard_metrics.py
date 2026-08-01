from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")


def _insights_row(timestamp: str, message: str) -> list[dict[str, str]]:
    return [{"field": "@timestamp", "value": timestamp}, {"field": "@message", "value": message}]


class StructuredLogSeriesTests(unittest.TestCase):
    def test_parses_matching_rows_and_converts_timestamp_to_utc_iso(self) -> None:
        results = [
            _insights_row("2026-07-30 21:14:13.172", '{"event": "scan_summary", "new": 3}'),
            _insights_row("2026-07-30 21:13:35.352", '{"event": "scan_summary", "new": 5}'),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._structured_log_series("scan_summary", 24)

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["timestamp"], datetime(2026, 7, 30, 21, 13, 35, 352000, tzinfo=timezone.utc).isoformat())
        self.assertEqual(series[1]["timestamp"], datetime(2026, 7, 30, 21, 14, 13, 172000, tzinfo=timezone.utc).isoformat())

    def test_skips_unparseable_and_mismatched_rows(self) -> None:
        results = [
            _insights_row("2026-07-30 21:00:00.000", "not json"),
            _insights_row("2026-07-30 21:01:00.000", '{"event": "other_event", "count": 1}'),
            _insights_row("2026-07-30 21:02:00.000", '{"event": "validator_backlog", "count": 7}'),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._structured_log_series("validator_backlog", 24)

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["count"], 7)

    def test_sorts_rows_by_timestamp_ascending(self) -> None:
        results = [
            _insights_row("2026-07-30 21:05:00.000", '{"event": "scan_summary", "new": 2}'),
            _insights_row("2026-07-30 21:01:00.000", '{"event": "scan_summary", "new": 1}'),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._structured_log_series("scan_summary", 24)

        self.assertEqual([item["new"] for item in series], [1, 2])

    def test_polls_until_query_completes(self) -> None:
        responses = [
            {"status": "Running", "results": []},
            {"status": "Running", "results": []},
            {"status": "Complete", "results": [_insights_row("2026-07-30 21:00:00.000", '{"event": "scan_summary", "new": 9}')]},
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", side_effect=responses) as mock_results:
                with patch("app.time.sleep"):
                    series = app._structured_log_series("scan_summary", 24)

        self.assertEqual(mock_results.call_count, 3)
        self.assertEqual(series[0]["new"], 9)

    def test_returns_empty_when_query_never_completes(self) -> None:
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Running", "results": []}):
                with patch("app.time.sleep"):
                    series = app._structured_log_series("scan_summary", 24)

        self.assertEqual(series, [])


def _bucket_row(bucket: str, input_tokens: str, output_tokens: str) -> list[dict[str, str]]:
    return [
        {"field": "bucket", "value": bucket},
        {"field": "input_tokens", "value": input_tokens},
        {"field": "output_tokens", "value": output_tokens},
    ]


class TokenUsageSeriesTests(unittest.TestCase):
    """minutes here means minutes (60s bins per _insights_bin_seconds, since
    e.g. 10*60=600s / 60s = 10 <= 200) - not the hours used elsewhere in this
    file. time.time() is mocked so zero-filled bucket boundaries are
    deterministic instead of depending on when the test happens to run."""

    def test_parses_a_real_bucket_and_zero_fills_the_rest(self) -> None:
        fake_now = datetime(2026, 7, 30, 21, 5, 0, tzinfo=timezone.utc).timestamp()
        results = [_bucket_row("2026-07-30 21:00:00.000", "61026", "64701")]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                with patch("app.time.time", return_value=fake_now):
                    series = app._token_usage_series(10)

        by_timestamp = {item["timestamp"]: item for item in series}
        real_bucket = datetime(2026, 7, 30, 21, 0, 0, tzinfo=timezone.utc).isoformat()
        self.assertEqual(by_timestamp[real_bucket]["input_tokens"], 61026)
        self.assertEqual(by_timestamp[real_bucket]["output_tokens"], 64701)
        other_buckets = [item for ts, item in by_timestamp.items() if ts != real_bucket]
        self.assertTrue(other_buckets)
        self.assertTrue(all(item["input_tokens"] == 0 and item["output_tokens"] == 0 for item in other_buckets))

    def test_sorts_buckets_ascending(self) -> None:
        fake_now = datetime(2026, 7, 30, 22, 5, 0, tzinfo=timezone.utc).timestamp()
        results = [
            _bucket_row("2026-07-30 22:00:00.000", "10", "20"),
            _bucket_row("2026-07-30 21:00:00.000", "5", "8"),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                with patch("app.time.time", return_value=fake_now):
                    series = app._token_usage_series(70)

        timestamps = [item["timestamp"] for item in series]
        self.assertEqual(timestamps, sorted(timestamps))
        by_timestamp = {item["timestamp"]: item for item in series}
        self.assertEqual(by_timestamp[datetime(2026, 7, 30, 21, 0, 0, tzinfo=timezone.utc).isoformat()]["input_tokens"], 5)
        self.assertEqual(by_timestamp[datetime(2026, 7, 30, 22, 0, 0, tzinfo=timezone.utc).isoformat()]["input_tokens"], 10)

    def test_zero_fills_the_whole_window_when_query_never_completes(self) -> None:
        fake_now = datetime(2026, 7, 30, 21, 5, 0, tzinfo=timezone.utc).timestamp()
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Running", "results": []}):
                with patch("app.time.sleep"):
                    with patch("app.time.time", return_value=fake_now):
                        series = app._token_usage_series(5)

        self.assertTrue(series)
        self.assertTrue(all(item["input_tokens"] == 0 and item["output_tokens"] == 0 for item in series))


class RecentLogEventsTests(unittest.TestCase):
    """Regression tests: FilterLogEvents (no pagination, no sort control) filled
    its result cap with the OLDEST events in the window, so the "newest at top"
    logs page was actually showing a stale slice no matter how it was sorted
    afterward. Now backed by Insights' own `sort @timestamp desc`."""

    def test_preserves_newest_first_order_from_the_query(self) -> None:
        results = [
            _insights_row("2026-07-30 21:14:00.000", "second newest line"),
            _insights_row("2026-07-30 21:13:00.000", "oldest line"),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                events = app._recent_log_events()

        self.assertEqual([event["message"] for event in events], ["second newest line", "oldest line"])

    def test_flags_failure_markers_and_strips_trailing_newline(self) -> None:
        results = [_insights_row("2026-07-30 21:14:00.000", "Traceback (most recent call last):\n")]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                events = app._recent_log_events()

        self.assertEqual(events[0]["message"], "Traceback (most recent call last):")
        self.assertTrue(events[0]["is_failure"])

    def test_classifier_dismissed_reason_containing_fail_is_not_flagged(self) -> None:
        """The classifier's own reasoning often contains "fails"/"Failure" as ordinary words, e.g. in a job title - not an actual failure."""
        results = [
            _insights_row(
                "2026-07-30 21:14:00.000",
                "User a@b.com: classifier dismissed: Pinterest - ML Intern (Fails multiple criteria: requires PhD)",
            ),
            _insights_row(
                "2026-07-30 21:15:00.000",
                "User a@b.com: validator rejected: Nvidia - Senior Opto-Mechanical Failure Analysis Engineer (junk)",
            ),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                events = app._recent_log_events()

        self.assertFalse(events[0]["is_failure"])
        self.assertFalse(events[1]["is_failure"])

    def test_real_source_failure_still_flagged(self) -> None:
        results = [_insights_row("2026-07-30 21:14:00.000", "Source 'direct:Example:intern' failed: HTTP 429")]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                events = app._recent_log_events()

        self.assertTrue(events[0]["is_failure"])

    def test_requests_the_newest_n_directly_via_query_string(self) -> None:
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}) as mock_start:
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": []}):
                app._recent_log_events(limit=200)

        query_string = mock_start.call_args.kwargs["queryString"]
        self.assertIn("sort @timestamp desc", query_string)
        self.assertIn("limit 200", query_string)


class PeriodScalingTests(unittest.TestCase):
    def test_metric_period_seconds_stays_fine_grained_for_short_windows(self) -> None:
        self.assertEqual(app._metric_period_seconds(5 * 60), 60)
        self.assertEqual(app._metric_period_seconds(3 * 3600), 60)

    def test_metric_period_seconds_scales_up_for_long_windows(self) -> None:
        self.assertEqual(app._metric_period_seconds(24 * 3600), 300)
        self.assertEqual(app._metric_period_seconds(7 * 24 * 3600), 3600)

    def test_insights_bin_expression_scales_with_window(self) -> None:
        self.assertEqual(app._insights_bin_expression(5 * 60), "1m")
        self.assertEqual(app._insights_bin_expression(24 * 3600), "15m")
        self.assertEqual(app._insights_bin_expression(7 * 24 * 3600), "1h")


class InvocationMetricsPeriodTests(unittest.TestCase):
    def test_errors_and_avg_duration_use_the_whole_window_as_one_bucket(self) -> None:
        """Regression test: these were hardcoded to period=86400, which was only
        correct because the window was always a hardcoded 24h too - now that the
        window is selectable, the period must equal it, or "latest" would only
        reflect the last sub-bucket instead of the whole selected range."""
        captured: dict[str, Any] = {}

        def fake_get_metric_data(**kwargs: Any) -> dict[str, Any]:
            captured["queries"] = kwargs["MetricDataQueries"]
            return {
                "MetricDataResults": [
                    {"Id": "invocations", "Values": [1, 2]},
                    {"Id": "errors", "Values": [0]},
                    {"Id": "avg_duration_ms", "Values": [123.45]},
                ]
            }

        with patch.object(app.cloudwatch_client, "get_metric_data", side_effect=fake_get_metric_data):
            app._invocation_metrics(start_time=0, end_time=3600)

        periods = {query["Id"]: query["MetricStat"]["Period"] for query in captured["queries"]}
        self.assertEqual(periods["errors"], 3600)
        self.assertEqual(periods["avg_duration_ms"], 3600)

    def test_result_keys_are_not_hardcoded_to_24h(self) -> None:
        with patch.object(
            app.cloudwatch_client,
            "get_metric_data",
            return_value={
                "MetricDataResults": [
                    {"Id": "invocations", "Values": [1, 2]},
                    {"Id": "errors", "Values": [1]},
                    {"Id": "avg_duration_ms", "Values": [50.0]},
                ]
            },
        ):
            result = app._invocation_metrics(start_time=0, end_time=300)

        self.assertEqual(result, {"invocations": 3, "errors": 1, "avg_duration_ms": 50.0})


class RecentMetricsCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        app._metrics_cache = {}

    def _patch_dependencies(self):
        return (
            patch.object(app, "_invocation_metrics", return_value={"invocations": 1}),
            patch.object(app, "_last_invocation_time", return_value=None),
            patch.object(app, "_duration_series", return_value=[]),
            patch.object(app, "_structured_log_series", return_value=[]),
            patch.object(app, "_token_usage_series", return_value=[]),
        )

    def test_returns_cached_result_without_recomputing_within_ttl(self) -> None:
        invocation_patch, last_ran_patch, duration_patch, structured_patch, token_patch = self._patch_dependencies()
        with invocation_patch as mock_invocation, last_ran_patch, duration_patch, structured_patch, token_patch:
            first = app._recent_metrics()
            second = app._recent_metrics()

        self.assertEqual(first, second)
        mock_invocation.assert_called_once()

    def test_recomputes_after_ttl_expires(self) -> None:
        invocation_patch, last_ran_patch, duration_patch, structured_patch, token_patch = self._patch_dependencies()
        with invocation_patch as mock_invocation, last_ran_patch, duration_patch, structured_patch, token_patch:
            app._recent_metrics()
            cached_at, cached_result = app._metrics_cache[1440]
            app._metrics_cache[1440] = (cached_at - app.METRICS_CACHE_TTL_SECONDS - 1, cached_result)
            app._recent_metrics()

        self.assertEqual(mock_invocation.call_count, 2)

    def test_different_ranges_are_cached_independently(self) -> None:
        invocation_patch, last_ran_patch, duration_patch, structured_patch, token_patch = self._patch_dependencies()
        with invocation_patch as mock_invocation, last_ran_patch, duration_patch, structured_patch, token_patch:
            app._recent_metrics(60)
            app._recent_metrics(1440)

        self.assertEqual(mock_invocation.call_count, 2)
        self.assertIn(60, app._metrics_cache)
        self.assertIn(1440, app._metrics_cache)


def _user_row(user_id: str, input_tokens: str, output_tokens: str) -> list[dict[str, str]]:
    return [
        {"field": "raw_user_id", "value": user_id},
        {"field": "input_tokens", "value": input_tokens},
        {"field": "output_tokens", "value": output_tokens},
    ]


class TokenUsageByUserTests(unittest.TestCase):
    def test_parses_per_user_token_totals(self) -> None:
        results = [_user_row("a@example.com", "100", "200"), _user_row("b@example.com", "50", "60")]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                usage = app._token_usage_by_user(60)

        self.assertEqual(
            usage,
            [
                {"user_id": "a@example.com", "input_tokens": 100, "output_tokens": 200},
                {"user_id": "b@example.com", "input_tokens": 50, "output_tokens": 60},
            ],
        )

    def test_missing_user_id_falls_back_to_unknown(self) -> None:
        # Insights omits the grouping field entirely when empty for every match (pre-user_id log lines).
        results = [[{"field": "input_tokens", "value": "10"}, {"field": "output_tokens", "value": "20"}]]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                usage = app._token_usage_by_user(60)

        self.assertEqual(usage, [{"user_id": "unknown", "input_tokens": 10, "output_tokens": 20}])


class NotificationsByUserTests(unittest.TestCase):
    def test_filters_to_notified_and_sorts_newest_first(self) -> None:
        items = [
            {"status": "notified", "seen_at": 100, "company_name": "A", "title": "Old", "url": "u1", "fit_score": 80},
            {"status": "dismissed", "seen_at": 200, "company_name": "B", "title": "Nope", "url": "u2"},
            {"status": "notified", "seen_at": 300, "company_name": "C", "title": "New", "url": "u3", "fit_score": 90},
        ]
        with patch.object(app, "list_all_users", return_value=[{"user_id": "a@example.com"}]):
            with patch.object(app, "list_seen_listings", return_value=items):
                result = app._notifications_by_user(60)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["user_id"], "a@example.com")
        self.assertEqual([n["title"] for n in result[0]["notifications"]], ["New", "Old"])

    def test_returns_empty_list_with_no_users(self) -> None:
        with patch.object(app, "list_all_users", return_value=[]):
            self.assertEqual(app._notifications_by_user(60), [])

    def test_looks_up_each_user_independently(self) -> None:
        with patch.object(app, "list_all_users", return_value=[{"user_id": "a@example.com"}, {"user_id": "b@example.com"}]):
            with patch.object(app, "list_seen_listings", return_value=[]) as mock_list:
                app._notifications_by_user(60)

        called_user_ids = {call.args[0] for call in mock_list.call_args_list}
        self.assertEqual(called_user_ids, {"a@example.com", "b@example.com"})


class AdminActivityCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        app._admin_activity_cache = {}

    def test_caches_within_ttl(self) -> None:
        with patch.object(app, "_token_usage_by_user", return_value=[]) as mock_token:
            with patch.object(app, "_notifications_by_user", return_value=[]):
                app._admin_activity(1440)
                app._admin_activity(1440)

        mock_token.assert_called_once()


if __name__ == "__main__":
    unittest.main()
