from __future__ import annotations

import unittest
from unittest.mock import patch

import users


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


if __name__ == "__main__":
    unittest.main()
