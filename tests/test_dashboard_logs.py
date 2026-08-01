from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "watch"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")


def _event(timestamp: str, message: str, is_failure: bool = False) -> dict[str, object]:
    return {"timestamp": timestamp, "message": message, "is_failure": is_failure}


def _insights_row(timestamp: str, message: str) -> list[dict[str, str]]:
    return [{"field": "@timestamp", "value": timestamp}, {"field": "@message", "value": message}]


class GroupLogRunsTests(unittest.TestCase):
    """Python port of frontend/src/lib/groupLogRuns.test.ts - same cases, ascending
    input (this port's own contract; the TS original takes descending)."""

    def test_report_after_end_still_attributes_by_request_id(self) -> None:
        ascending = [
            _event("2026-07-31T00:00:00Z", "START RequestId: req-1 Version: $LATEST"),
            _event("2026-07-31T00:00:01Z", "Scan complete: 1 user(s)"),
            _event("2026-07-31T00:00:02Z", "END RequestId: req-1"),
            _event("2026-07-31T00:00:03Z", "START RequestId: req-2 Version: $LATEST"),
            _event("2026-07-31T00:00:04Z", "Source 'apple' failed: boom", is_failure=True),
            _event("2026-07-31T00:00:05Z", "END RequestId: req-2"),
            _event("2026-07-31T00:00:06Z", "REPORT RequestId: req-2\tDuration: 1234.56 ms\tBilled..."),
        ]

        runs = app._group_log_runs(ascending)

        self.assertEqual(len(runs), 2, "no phantom run for the post-END REPORT line")
        self.assertEqual(runs[0]["id"], "req-2", "newest run comes first")
        self.assertEqual(runs[1]["id"], "req-1")
        self.assertEqual(runs[0]["durationMs"], 1234.56)
        self.assertEqual(runs[0]["failureCount"], 1)
        self.assertEqual(runs[0]["startTime"], "2026-07-31T00:00:03Z")
        self.assertEqual(runs[0]["endTime"], "2026-07-31T00:00:05Z")
        self.assertEqual(len(runs[0]["lines"]), 4, "START + failure + END + REPORT")
        self.assertEqual(runs[1]["failureCount"], 0)
        self.assertIsNone(runs[1]["durationMs"])
        self.assertEqual(len(runs[1]["lines"]), 3, "START + print + END")

    def test_lines_before_first_start_land_in_a_synthetic_unknown_run(self) -> None:
        ascending = [
            _event("2026-07-31T00:00:00Z", "leftover line from a run that started before the window"),
            _event("2026-07-31T00:00:01Z", "START RequestId: req-3 Version: $LATEST"),
        ]

        runs = app._group_log_runs(ascending)

        self.assertEqual(len(runs), 2)
        self.assertTrue(any(run["id"] is None and len(run["lines"]) == 1 for run in runs))

    def test_empty_input(self) -> None:
        self.assertEqual(app._group_log_runs([]), [])


class ParseLogEventRowTests(unittest.TestCase):
    def test_strips_node_runtime_prefix(self) -> None:
        row = _insights_row(
            "2026-08-01 16:37:53.799",
            "2026-08-01T16:37:53.799Z 460356c3-25af-4cb0-97fd-7b81e6fbbd15 INFO [renderer] starting",
        )

        event = app._parse_log_event_row(row)

        assert event is not None
        self.assertEqual(event["message"], "[renderer] starting")

    def test_leaves_message_without_runtime_prefix_untouched(self) -> None:
        row = _insights_row("2026-08-01 16:37:53.799", "START RequestId: abc Version: $LATEST")

        event = app._parse_log_event_row(row)

        assert event is not None
        self.assertEqual(event["message"], "START RequestId: abc Version: $LATEST")


class IsFailureLineTests(unittest.TestCase):
    """scan_summary's own "sources_failed" key contains the substring "fail" even at
    count 0 - structured {"event": ...} lines must be judged by field, not substring."""

    def test_scan_summary_with_zero_failures_is_not_a_failure(self) -> None:
        message = '{"event": "scan_summary", "users": 7, "new": 0, "notified": 0, "dismissed": 0, "run_duration_ms": 30242, "sources_scanned": 36, "sources_failed": 0}'
        self.assertFalse(app._is_failure_line(message))

    def test_scan_summary_with_nonzero_failures_is_a_failure(self) -> None:
        message = '{"event": "scan_summary", "sources_failed": 2}'
        self.assertTrue(app._is_failure_line(message))

    def test_source_fetch_success_is_not_a_failure(self) -> None:
        self.assertFalse(app._is_failure_line('{"event": "source_fetch", "source": "apple", "success": true}'))

    def test_source_fetch_failure_is_a_failure(self) -> None:
        self.assertTrue(app._is_failure_line('{"event": "source_fetch", "source": "apple", "success": false}'))

    def test_render_failure_event_is_always_a_failure(self) -> None:
        self.assertTrue(app._is_failure_line('{"event": "render_failure", "url": "https://example.com"}'))

    def test_render_success_event_is_not_a_failure(self) -> None:
        self.assertFalse(app._is_failure_line('{"event": "render_success", "url": "https://example.com"}'))

    def test_unrecognized_structured_event_defaults_to_not_a_failure(self) -> None:
        self.assertFalse(app._is_failure_line('{"event": "auth_rejected", "reason": "rate_limited"}'))

    def test_plain_text_failure_line_still_detected(self) -> None:
        self.assertTrue(app._is_failure_line("Source 'apple' failed: boom"))

    def test_plain_text_traceback_still_detected(self) -> None:
        self.assertTrue(app._is_failure_line("Traceback (most recent call last):"))

    def test_classifier_reason_prose_is_not_a_failure(self) -> None:
        self.assertFalse(app._is_failure_line("User x: classifier dismissed: Acme - Intern (Fails multiple criteria)"))

    def test_non_json_message_falls_back_to_substring_check(self) -> None:
        self.assertFalse(app._is_failure_line("Scan complete: 7 user(s), 0 new"))


class RunBoundariesTests(unittest.TestCase):
    def test_returns_request_id_and_start_epoch_newest_first(self) -> None:
        results = [
            _insights_row("2026-08-01 00:00:00.000", "START RequestId: run2 Version: $LATEST"),
            _insights_row("2026-07-31 23:55:00.000", "START RequestId: run1 Version: $LATEST"),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                boundaries = app._run_boundaries(app.WATCH_LOG_GROUP, 1785600000, 2, app.RUN_LOOKBACK_MINUTES)

        self.assertEqual([request_id for request_id, _ in boundaries], ["run2", "run1"])
        expected_epoch = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        self.assertAlmostEqual(boundaries[0][1], expected_epoch, delta=1)


class FetchRunsPageTests(unittest.TestCase):
    def test_no_boundaries_returns_empty_page(self) -> None:
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": []}):
                page = app._fetch_runs_page(app.WATCH_LOG_GROUP, None, 5)

        self.assertEqual(page, {"runs": [], "next_cursor": None})

    def test_two_query_page_groups_and_filters_to_boundary_ids(self) -> None:
        boundary_results = {"status": "Complete", "results": [_insights_row("2026-08-01 00:00:03.000", "START RequestId: req-1 Version: $LATEST")]}
        raw_line_results = {
            "status": "Complete",
            "results": [
                _insights_row("2026-08-01 00:00:03.000", "START RequestId: req-1 Version: $LATEST"),
                _insights_row("2026-08-01 00:00:04.000", "hello"),
                _insights_row("2026-08-01 00:00:05.000", "END RequestId: req-1"),
            ],
        }
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", side_effect=[boundary_results, raw_line_results]) as mock_results:
                page = app._fetch_runs_page(app.WATCH_LOG_GROUP, None, 1)

        self.assertEqual(mock_results.call_count, 2, "one boundary query, one raw-lines query")
        self.assertEqual(len(page["runs"]), 1)
        self.assertEqual(page["runs"][0]["id"], "req-1")
        self.assertEqual(len(page["runs"][0]["lines"]), 3)

    def test_next_cursor_is_none_when_fewer_than_count_boundaries_found(self) -> None:
        """Fewer boundaries than requested means the lookback window's edge was hit - no more pages."""
        boundary_results = {"status": "Complete", "results": [_insights_row("2026-08-01 00:00:03.000", "START RequestId: req-1 Version: $LATEST")]}
        raw_line_results = {"status": "Complete", "results": [_insights_row("2026-08-01 00:00:03.000", "START RequestId: req-1 Version: $LATEST")]}
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", side_effect=[boundary_results, raw_line_results]):
                page = app._fetch_runs_page(app.WATCH_LOG_GROUP, None, 5)

        self.assertIsNone(page["next_cursor"])

    def test_next_cursor_excludes_the_oldest_run_from_the_next_page(self) -> None:
        """A full page (len(boundaries) == count) returns a cursor 1s before the oldest
        run's start, so the next page's window strictly excludes it - Insights' endTime
        is inclusive, so reusing the exact boundary would duplicate that run."""
        boundary_results = {
            "status": "Complete",
            "results": [_insights_row(f"2026-08-01 00:00:0{i}.000", f"START RequestId: req-{i}") for i in range(2)],
        }
        raw_line_results = {"status": "Complete", "results": boundary_results["results"]}
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", side_effect=[boundary_results, raw_line_results]):
                page = app._fetch_runs_page(app.WATCH_LOG_GROUP, None, 2)

        oldest_epoch = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        self.assertEqual(page["next_cursor"], oldest_epoch - 1)


class SearchLogLinesTests(unittest.TestCase):
    def test_returns_matching_lines_newest_first(self) -> None:
        results = [
            _insights_row("2026-08-01 00:00:05.000", "Source 'apple' failed: boom"),
            _insights_row("2026-08-01 00:00:00.000", "Source 'apple' failed: earlier boom"),
        ]
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}) as mock_start:
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": results}):
                page = app._search_log_lines(app.WATCH_LOG_GROUP, "apple", None, 200)

        self.assertEqual(len(page["events"]), 2)
        self.assertIn("apple", page["events"][0]["message"])
        sent_query = mock_start.call_args.kwargs["queryString"]
        self.assertIn('like "apple"', sent_query)

    def test_quotes_and_backslashes_are_escaped_not_executed_as_regex(self) -> None:
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}) as mock_start:
            with patch.object(app.logs_client, "get_query_results", return_value={"status": "Complete", "results": []}):
                app._search_log_lines(app.WATCH_LOG_GROUP, 'a"b\\c', None, 200)

        sent_query = mock_start.call_args.kwargs["queryString"]
        self.assertIn('like "a\\"b\\\\c"', sent_query)

    def test_next_cursor_set_only_when_page_is_full(self) -> None:
        one_result = {"status": "Complete", "results": [_insights_row("2026-08-01 00:00:00.000", "match")]}
        with patch.object(app.logs_client, "start_query", return_value={"queryId": "q1"}):
            with patch.object(app.logs_client, "get_query_results", return_value=one_result):
                full_page = app._search_log_lines(app.WATCH_LOG_GROUP, "match", None, 1)
                short_page = app._search_log_lines(app.WATCH_LOG_GROUP, "match", None, 5)

        self.assertIsNotNone(full_page["next_cursor"])
        self.assertIsNone(short_page["next_cursor"])


class LogGroupResolutionTests(unittest.TestCase):
    """The /api/logs handler resolves `lambda` against this fixed allowlist rather
    than passing user input straight through to the CloudWatch API call - an
    unrecognized or missing value must fall back to watch, never error or pass through."""

    def test_each_known_key_resolves_to_its_own_log_group(self) -> None:
        self.assertEqual(app.LOG_GROUPS_BY_LAMBDA["watch"], app.WATCH_LOG_GROUP)
        self.assertEqual(app.LOG_GROUPS_BY_LAMBDA["dashboard"], app.DASHBOARD_LOG_GROUP)
        self.assertEqual(app.LOG_GROUPS_BY_LAMBDA["renderer"], app.RENDERER_LOG_GROUP)

    def test_unknown_or_missing_value_falls_back_to_watch(self) -> None:
        fallback = app.LOG_GROUPS_BY_LAMBDA[app.DEFAULT_LAMBDA_KEY]
        self.assertEqual(app.LOG_GROUPS_BY_LAMBDA.get("nonsense", fallback), app.WATCH_LOG_GROUP)
        self.assertEqual(app.LOG_GROUPS_BY_LAMBDA.get("", fallback), app.WATCH_LOG_GROUP)


if __name__ == "__main__":
    unittest.main()
