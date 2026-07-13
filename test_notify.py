#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from notifiers import NotificationError, notify
from sources.base import Listing

TEST_LISTING = Listing(
    source="test",
    id="test",
    company_name="Test Co",
    title="Test Notification",
    locations=["Nowhere"],
    url="https://example.com",
)


def main() -> int:
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    email_to = os.environ.get("EMAIL_TO")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not ntfy_topic or not email_to or not smtp_user or not smtp_pass:
        print(
            "Missing required environment variables: NTFY_TOPIC, EMAIL_TO, SMTP_USER, SMTP_PASS",
            file=sys.stderr,
        )
        return 1

    try:
        notify(ntfy_topic, smtp_user, smtp_pass, email_to, TEST_LISTING)
    except NotificationError as error:
        print(f"Test notification failed: {error}", file=sys.stderr)
        return 1

    print("Test notification sent via ntfy and email.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
