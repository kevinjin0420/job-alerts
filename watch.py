#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

from classifier import ClassifierError, is_good_fit
from config import load_config
from notifiers import NotificationError, notify
from sources import Listing, Source, build_sources
from storage import load_seen_ids, save_seen_ids, seen_file_exists

DEFAULT_ENABLED_SOURCES = ["community"]


def _string_list(config: dict[str, object], key: str) -> list[str]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def get_target_companies(config: dict[str, object]) -> list[str]:
    return _string_list(config, "companies")


def get_email_recipients(config: dict[str, object]) -> list[str]:
    return _string_list(config, "email_to")


def get_enabled_source_specs(config: dict[str, object]) -> list[str]:
    return _string_list(config, "enabled_sources") or DEFAULT_ENABLED_SOURCES


def passes_classifier(openrouter_api_key: str | None, classifier_model: str, fit_prompt: str, listing: Listing) -> bool:
    """True means "notify". Disabled (no key, no prompt, or unedited placeholder
    prompt) and any API failure both fail open rather than silently suppressing
    a real listing."""
    if not openrouter_api_key or not fit_prompt or fit_prompt.startswith("PLACEHOLDER"):
        return True
    try:
        return is_good_fit(openrouter_api_key, classifier_model, fit_prompt, listing)
    except ClassifierError as error:
        print(
            f"Classifier failed for {listing.company_name} - {listing.title}, notifying anyway: {error}",
            file=sys.stderr,
        )
        return True


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
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not ntfy_topic or not smtp_user or not smtp_pass:
        print(
            "Missing required environment variables: NTFY_TOPIC, SMTP_USER, SMTP_PASS",
            file=sys.stderr,
        )
        return 1

    config = load_config()
    email_recipients = get_email_recipients(config)
    if not email_recipients:
        print("Missing required config: email_to", file=sys.stderr)
        return 1

    try:
        sources = build_sources(get_enabled_source_specs(config), get_target_companies(config))
    except ValueError as error:
        print(f"Invalid enabled_sources configuration: {error}", file=sys.stderr)
        return 1

    fit_prompt = str(config.get("fit_prompt", ""))
    classifier_model = str(config.get("classifier_model", ""))
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")

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
    rejected_ids: set[str] = set()
    had_notification_failure = False

    for listing in new_listings:
        if not passes_classifier(openrouter_api_key, classifier_model, fit_prompt, listing):
            rejected_ids.add(listing.unique_id)
            print(f"Classifier rejected: {listing.company_name} - {listing.title}")
            continue
        try:
            notify(ntfy_topic, smtp_user, smtp_pass, email_recipients, listing)
        except NotificationError as error:
            had_notification_failure = True
            print(
                f"Failed to notify for {listing.company_name} - {listing.title}: {error}",
                file=sys.stderr,
            )
            continue
        successfully_notified_ids.add(listing.unique_id)
        print(f"Notified: {listing.company_name} - {listing.title}")

    # Notify-failures stay out of seen_ids so they're retried next run.
    # Classifier-rejected listings go in so they aren't reclassified (and rebilled) every run.
    save_seen_ids(seen_ids | successfully_notified_ids | rejected_ids)
    print(
        f"Scan complete: {len(new_listings)} new, {len(successfully_notified_ids)} notified, "
        f"{len(rejected_ids)} rejected by classifier"
    )
    return 1 if had_notification_failure else 0


if __name__ == "__main__":
    sys.exit(main())
