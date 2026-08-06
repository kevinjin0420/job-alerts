from __future__ import annotations

import unittest
from unittest.mock import patch

import users
from sources.base import Listing


def _entry(listing_id: str) -> tuple[Listing, str, str, int | None]:
    listing = Listing(
        source="direct",
        id=listing_id,
        company_name="Example",
        title=f"Intern {listing_id}",
        locations=["Remote"],
        url=f"https://example.com/{listing_id}",
    )
    return listing, "seeded", "", None


def _seen_listing(listing_id: str, seen_at: int) -> dict[str, object]:
    return users._wrap_item(
        {
            "user_id": "test-user",
            "listing_id": listing_id,
            "seen_at": seen_at,
            "status": "notified",
            "company_name": "Example",
            "title": "Intern",
            "url": "https://example.com",
            "source": "direct",
        }
    )


class ListSeenListingsSinceFilterTests(unittest.TestCase):
    """Regression tests: /api/listings used to only ever return the most recent
    300 items, then filtered client-side by a selected time range - if the range
    didn't overlap that fixed slice, older matching listings within it never
    showed up at all. since filters server-side over the full history instead."""

    def test_default_behavior_unchanged_without_since(self) -> None:
        items = [_seen_listing(str(i), seen_at=i) for i in range(5)]
        with patch.object(users._dynamodb, "query", return_value={"Items": items}):
            result = users.list_seen_listings("test-user", limit=3)

        self.assertEqual(len(result), 3)
        self.assertEqual([item["listing_id"] for item in result], ["4", "3", "2"])

    def test_since_returns_every_match_regardless_of_limit(self) -> None:
        items = [_seen_listing(str(i), seen_at=i * 1000) for i in range(400)]
        with patch.object(users._dynamodb, "query", return_value={"Items": items}):
            result = users.list_seen_listings("test-user", limit=300, since=350000)

        self.assertEqual(len(result), 50)
        self.assertTrue(all(item["seen_at"] >= 350000 for item in result))

    def test_since_excludes_older_items(self) -> None:
        items = [_seen_listing("old", seen_at=100), _seen_listing("new", seen_at=200)]
        with patch.object(users._dynamodb, "query", return_value={"Items": items}):
            result = users.list_seen_listings("test-user", since=150)

        self.assertEqual([item["listing_id"] for item in result], ["new"])


class RecordListingsBatchingTests(unittest.TestCase):
    """A new user's first run seeds every listing every source produced at once - one
    put_item per listing ate the watch Lambda's timeout budget on sequential round trips."""

    def test_writes_are_chunked_to_dynamodbs_per_batch_cap(self) -> None:
        entries = [_entry(str(index)) for index in range(60)]
        with patch.object(users._dynamodb, "batch_write_item", return_value={}) as mock_batch:
            users.record_listings("test-user", entries)

        batch_sizes = [len(call.kwargs["RequestItems"][users.SEEN_LISTINGS_TABLE]) for call in mock_batch.call_args_list]
        self.assertEqual(batch_sizes, [25, 25, 10])

    def test_unprocessed_items_are_retried_not_dropped(self) -> None:
        entries = [_entry("1"), _entry("2")]
        first_call_items: list[dict[str, object]] = []

        def throttle_once(**kwargs: object) -> dict[str, object]:
            request_items = kwargs["RequestItems"]
            assert isinstance(request_items, dict)
            batch = request_items[users.SEEN_LISTINGS_TABLE]
            if not first_call_items:
                first_call_items.extend(batch)
                return {"UnprocessedItems": {users.SEEN_LISTINGS_TABLE: batch[:1]}}
            return {}

        with patch.object(users._dynamodb, "batch_write_item", side_effect=throttle_once) as mock_batch:
            with patch.object(users.time, "sleep"):
                users.record_listings("test-user", entries)

        self.assertEqual(mock_batch.call_count, 2)
        self.assertEqual(len(mock_batch.call_args_list[1].kwargs["RequestItems"][users.SEEN_LISTINGS_TABLE]), 1)

    def test_permanently_unprocessed_items_raise_rather_than_silently_vanish(self) -> None:
        always_throttled = {"UnprocessedItems": {users.SEEN_LISTINGS_TABLE: [{"PutRequest": {"Item": {}}}]}}
        with patch.object(users._dynamodb, "batch_write_item", return_value=always_throttled):
            with patch.object(users.time, "sleep"):
                with self.assertRaises(RuntimeError):
                    users.record_listings("test-user", [_entry("1")])

    def test_no_entries_issues_no_writes(self) -> None:
        with patch.object(users._dynamodb, "batch_write_item") as mock_batch:
            users.record_listings("test-user", [])

        mock_batch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
