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
            _insights_row("2026-07-30 21:02:00.000", '{"event": "classifier_backlog", "count": 7}'),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._structured_log_series("classifier_backlog", 24)

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
    def test_parses_bucketed_sums_and_converts_timestamp(self) -> None:
        results = [_bucket_row("2026-07-30 21:00:00.000", "61026", "64701")]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._token_usage_series(24)

        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["input_tokens"], 61026)
        self.assertEqual(series[0]["output_tokens"], 64701)
        self.assertEqual(series[0]["timestamp"], datetime(2026, 7, 30, 21, 0, 0, tzinfo=timezone.utc).isoformat())

    def test_sorts_buckets_ascending(self) -> None:
        results = [
            _bucket_row("2026-07-30 22:00:00.000", "10", "20"),
            _bucket_row("2026-07-30 21:00:00.000", "5", "8"),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                series = app._token_usage_series(24)

        self.assertEqual([item["input_tokens"] for item in series], [5, 10])

    def test_returns_empty_when_query_never_completes(self) -> None:
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Running", "results": []}):
                with patch("app.time.sleep"):
                    series = app._token_usage_series(24)

        self.assertEqual(series, [])


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


if __name__ == "__main__":
    unittest.main()
