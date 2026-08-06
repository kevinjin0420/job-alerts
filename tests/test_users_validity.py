from __future__ import annotations

import unittest
from unittest.mock import patch

import users


class SaveListingValidityTtlTests(unittest.TestCase):
    """A wrong rejection used to be permanent, black-holing a real posting for every user
    forever. Rejections now expire; acceptances still never do (see save_listing_validity)."""

    def _saved_item(self, *, is_job_posting: bool) -> dict[str, object]:
        with patch.object(users._dynamodb, "put_item") as mock_put:
            users.save_listing_validity("direct:1", is_job_posting=is_job_posting, reason="because")
        return users._unwrap_item(mock_put.call_args.kwargs["Item"])

    def test_rejection_expires(self) -> None:
        item = self._saved_item(is_job_posting=False)

        self.assertIn("ttl", item)
        self.assertGreater(item["ttl"], item["checked_at"])

    def test_acceptance_is_kept_forever(self) -> None:
        item = self._saved_item(is_job_posting=True)

        self.assertNotIn("ttl", item)

    def test_rejection_ttl_matches_the_configured_window(self) -> None:
        item = self._saved_item(is_job_posting=False)

        self.assertEqual(int(item["ttl"]) - int(item["checked_at"]), users.LISTING_REJECTION_TTL_SECONDS)


class RetryListingTests(unittest.TestCase):
    """Retry used to clear only the per-user seen row, so a listing the validator wrongly
    rejected hit its cached verdict again and never reached the classifier."""

    def test_clears_both_the_seen_row_and_the_cached_verdict(self) -> None:
        with patch.object(users._dynamodb, "delete_item") as mock_delete:
            users.retry_listing("user@example.com", "direct:1")

        deleted = [(call.kwargs["TableName"], call.kwargs["Key"]) for call in mock_delete.call_args_list]
        self.assertIn((users.SEEN_LISTINGS_TABLE, {"user_id": {"S": "user@example.com"}, "listing_id": {"S": "direct:1"}}), deleted)
        self.assertIn((users.LISTING_VALIDITY_TABLE, {"listing_id": {"S": "direct:1"}}), deleted)


if __name__ == "__main__":
    unittest.main()
