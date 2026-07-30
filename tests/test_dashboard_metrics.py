from __future__ import annotations

import importlib
import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("COGNITO_USER_POOL_ID", "test-pool")
os.environ.setdefault("COGNITO_CLIENT_ID", "test-client")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "dashboard"))
app = importlib.import_module("app")


class StructuredLogSeriesTests(unittest.TestCase):
    def test_parses_matching_events_and_attaches_timestamp(self) -> None:
        events = [
            {"timestamp": 1000, "message": '{"event": "scan_summary", "new": 3}'},
            {"timestamp": 2000, "message": '{"event": "scan_summary", "new": 5}'},
        ]
        with patch.object(app.logs_client, "filter_log_events", return_value={"events": events}):
            series = app._structured_log_series("scan_summary", 24)

        self.assertEqual(len(series), 2)
        self.assertEqual(series[0]["new"], 3)
        self.assertEqual(series[0]["timestamp"], datetime.fromtimestamp(1, tz=timezone.utc).isoformat())

    def test_skips_unparseable_and_mismatched_events(self) -> None:
        events = [
            {"timestamp": 1000, "message": "not json"},
            {"timestamp": 2000, "message": '{"event": "other_event", "count": 1}'},
            {"timestamp": 3000, "message": '{"event": "classifier_backlog", "count": 7}'},
        ]
        with patch.object(app.logs_client, "filter_log_events", return_value={"events": events}):
            series = app._structured_log_series("classifier_backlog", 24)

        self.assertEqual(series, [{"event": "classifier_backlog", "count": 7, "timestamp": datetime.fromtimestamp(3, tz=timezone.utc).isoformat()}])

    def test_sorts_out_of_order_events_by_timestamp(self) -> None:
        events = [
            {"timestamp": 5000, "message": '{"event": "scan_summary", "new": 2}'},
            {"timestamp": 1000, "message": '{"event": "scan_summary", "new": 1}'},
        ]
        with patch.object(app.logs_client, "filter_log_events", return_value={"events": events}):
            series = app._structured_log_series("scan_summary", 24)

        self.assertEqual([item["new"] for item in series], [1, 2])

    def test_paginates_when_a_page_is_empty_but_next_token_is_present(self) -> None:
        """Regression test: filter_log_events can return zero events on a page
        while still returning nextToken - that must not be read as "no matches"."""
        pages = [
            {"events": [], "nextToken": "page-2"},
            {"events": [{"timestamp": 3000, "message": '{"event": "classifier_backlog", "count": 4}'}]},
        ]
        with patch.object(app.logs_client, "filter_log_events", side_effect=pages) as mock_filter:
            series = app._structured_log_series("classifier_backlog", 24)

        self.assertEqual(mock_filter.call_count, 2)
        self.assertEqual(len(series), 1)
        self.assertEqual(series[0]["count"], 4)

    def test_stops_after_max_pages_even_if_next_token_keeps_coming(self) -> None:
        with patch.object(
            app.logs_client, "filter_log_events", return_value={"events": [], "nextToken": "always-more"}
        ) as mock_filter:
            series = app._structured_log_series("classifier_backlog", 24)

        self.assertEqual(mock_filter.call_count, app.MAX_LOG_SCAN_PAGES)
        self.assertEqual(series, [])


if __name__ == "__main__":
    unittest.main()
