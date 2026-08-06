from __future__ import annotations

import smtplib
import unittest
import urllib.error
from unittest.mock import patch

from notifiers import notify, notify_message
from sources.base import Listing


def _listing(title: str, company_name: str = "Example") -> Listing:
    return Listing(
        source="direct",
        id=title,
        company_name=company_name,
        title=title,
        locations=["San Jose, CA"],
        url=f"https://example.com/{title}",
    )


class NotifyBatchingTests(unittest.TestCase):
    """One company publishing several matching roles in the same run used to send one
    ntfy push and one email per listing - a wall of near-identical alerts."""

    def test_single_listing_keeps_role_specific_subject_and_click_url(self) -> None:
        listing = _listing("SWE Intern")
        with patch("notifiers.send_ntfy_message") as mock_ntfy:
            with patch("notifiers.send_email_message") as mock_email:
                notify("topic", "user@example.com", "pass", ["to@example.com"], [listing])

        self.assertEqual(mock_ntfy.call_args.args[1], "New Example posting: SWE Intern")
        self.assertEqual(mock_ntfy.call_args.kwargs["click_url"], "https://example.com/SWE Intern")
        self.assertEqual(mock_email.call_args.args[3], "New Example posting: SWE Intern")

    def test_multiple_listings_send_one_message_listing_every_role(self) -> None:
        listings = [_listing("SWE Intern"), _listing("ML Intern"), _listing("Infra Intern")]
        with patch("notifiers.send_ntfy_message") as mock_ntfy:
            with patch("notifiers.send_email_message") as mock_email:
                notify("topic", "user@example.com", "pass", ["to@example.com"], listings)

        mock_ntfy.assert_called_once()
        mock_email.assert_called_once()
        self.assertEqual(mock_ntfy.call_args.args[1], "Example: 3 new postings")
        email_body = mock_email.call_args.args[4]
        for listing in listings:
            self.assertIn(listing.title, email_body)

    def test_ntfy_body_is_truncated_but_email_keeps_everything(self) -> None:
        listings = [_listing(f"Intern {index}") for index in range(20)]
        with patch("notifiers.send_ntfy_message") as mock_ntfy:
            with patch("notifiers.send_email_message") as mock_email:
                notify("topic", "user@example.com", "pass", ["to@example.com"], listings)

        self.assertIn("...and 12 more (see email)", mock_ntfy.call_args.args[2])
        self.assertIn("Intern 19", mock_email.call_args.args[4])

    def test_empty_listings_sends_nothing(self) -> None:
        with patch("notifiers.send_ntfy_message") as mock_ntfy:
            with patch("notifiers.send_email_message") as mock_email:
                notify("topic", "user@example.com", "pass", ["to@example.com"], [])

        mock_ntfy.assert_not_called()
        mock_email.assert_not_called()


class PartialDeliveryTests(unittest.TestCase):
    """A raise means "nothing was delivered, retry next run" - so one channel failing must
    not raise, or the channel that did work re-delivers the same alert every run after."""

    def test_email_failure_alone_does_not_raise(self) -> None:
        with patch("notifiers.send_ntfy_message"):
            with patch("notifiers.send_email_message", side_effect=smtplib.SMTPException("boom")):
                notify("topic", "user@example.com", "pass", ["to@example.com"], [_listing("SWE Intern")])

    def test_ntfy_failure_alone_does_not_raise(self) -> None:
        with patch("notifiers.send_ntfy_message", side_effect=urllib.error.URLError("boom")):
            with patch("notifiers.send_email_message"):
                notify("topic", "user@example.com", "pass", ["to@example.com"], [_listing("SWE Intern")])

    def test_both_channels_failing_raises(self) -> None:
        with patch("notifiers.send_ntfy_message", side_effect=urllib.error.URLError("ntfy down")):
            with patch("notifiers.send_email_message", side_effect=smtplib.SMTPException("smtp down")):
                with self.assertRaises(urllib.error.URLError):
                    notify("topic", "user@example.com", "pass", ["to@example.com"], [_listing("SWE Intern")])

    def test_email_still_attempted_after_ntfy_fails(self) -> None:
        with patch("notifiers.send_ntfy_message", side_effect=urllib.error.URLError("boom")):
            with patch("notifiers.send_email_message") as mock_email:
                notify("topic", "user@example.com", "pass", ["to@example.com"], [_listing("SWE Intern")])

        mock_email.assert_called_once()

    def test_admin_message_shares_the_same_partial_delivery_rule(self) -> None:
        with patch("notifiers.send_ntfy_message", side_effect=urllib.error.URLError("boom")):
            with patch("notifiers.send_email_message") as mock_email:
                notify_message("topic", "user@example.com", "pass", ["to@example.com"], "subject", "body")

        mock_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
