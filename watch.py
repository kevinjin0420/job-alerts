#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from notifiers import NotificationError, notify
from sources import Listing, Source, build_sources
from storage import load_seen_ids, save_seen_ids, seen_file_exists

DEFAULT_ENABLED_SOURCES = "community"
DEFAULT_COMPANIES = "Google"


def get_target_companies() -> list[str]:
    raw = os.environ.get("COMPANIES") or DEFAULT_COMPANIES
    return [name.strip() for name in raw.split(",") if name.strip()]


def get_enabled_source_specs() -> list[str]:
    raw = os.environ.get("ENABLED_SOURCES") or DEFAULT_ENABLED_SOURCES
    return [spec.strip() for spec in raw.split(",") if spec.strip()]


def fetch_all_listings(sources: list[Source]) -> list[Listing]:
    all_listings: list[Listing] = []
    for source in sources:
        try:
            listings = source.fetch()
        except Exception as error:  # a single broken source must not block the rest
            print(f"Source '{source.name}' failed: {error}", file=sys.stderr)
            continue
        print(f"Source '{source.name}': {len(listings)} matching listing(s)")
        all_listings.extend(listings)
    return all_listings


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
        sources = build_sources(get_enabled_source_specs(), get_target_companies())
    except ValueError as error:
        print(f"Invalid ENABLED_SOURCES configuration: {error}", file=sys.stderr)
        return 1

    is_first_run = not seen_file_exists()
    all_listings = fetch_all_listings(sources)
    seen_ids = load_seen_ids()

    if is_first_run:
        all_ids = {listing.unique_id for listing in all_listings}
        print(f"First run: seeding {len(all_ids)} existing listing(s) without notifying")
        save_seen_ids(all_ids)
        return 0

    new_listings = [listing for listing in all_listings if listing.unique_id not in seen_ids]
    successfully_notified_ids: set[str] = set()
    had_notification_failure = False

    for listing in new_listings:
        try:
            notify(ntfy_topic, smtp_user, smtp_pass, email_to, listing)
        except NotificationError as error:
            had_notification_failure = True
            print(
                f"Failed to notify for {listing.company_name} - {listing.title}: {error}",
                file=sys.stderr,
            )
            continue
        successfully_notified_ids.add(listing.unique_id)
        print(f"Notified: {listing.company_name} - {listing.title}")

    # Unnotified new listings stay out of seen_ids so they're retried next run.
    save_seen_ids(seen_ids | successfully_notified_ids)
    return 1 if had_notification_failure else 0


if __name__ == "__main__":
    sys.exit(main())
