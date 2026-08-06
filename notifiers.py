from __future__ import annotations

import smtplib
import sys
import urllib.error
import urllib.request
from email.mime.text import MIMEText

from sources.base import Listing

REQUEST_TIMEOUT_SECONDS = 30
NotificationError = (urllib.error.URLError, smtplib.SMTPException, OSError)
# ntfy rejects oversized message bodies; a company dumping 30 postings in one batch would
# hit that, so the push lists this many and points at the email for the rest.
NTFY_MAX_LISTINGS_PER_MESSAGE = 8


def send_ntfy_message(topic: str, title: str, body: str, click_url: str | None = None) -> None:
    headers = {"Title": title}
    if click_url:
        headers["Click"] = click_url
    request = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS):
        pass


def send_email_message(smtp_user: str, smtp_pass: str, email_to: list[str], subject: str, body: str) -> None:
    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = ", ".join(email_to)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=REQUEST_TIMEOUT_SECONDS) as server:
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, email_to, message.as_string())


def _send_both_channels(
    ntfy_topic: str,
    smtp_user: str,
    smtp_pass: str,
    email_to: list[str],
    subject: str,
    ntfy_body: str,
    email_body: str,
    click_url: str | None = None,
) -> None:
    """Raises only when BOTH channels fail. Callers treat a raise as "nothing was
    delivered, retry next run" - so a partial success must not raise, or the channel
    that did work re-delivers the same alert on every subsequent run."""
    failures: list[Exception] = []
    try:
        send_ntfy_message(ntfy_topic, subject, ntfy_body, click_url=click_url)
    except NotificationError as error:
        failures.append(error)
    try:
        send_email_message(smtp_user, smtp_pass, email_to, subject, email_body)
    except NotificationError as error:
        failures.append(error)
    if len(failures) == 2:
        raise failures[0]
    for error in failures:
        print(f"Notification partially failed (other channel delivered): {error}", file=sys.stderr)


def _format_listing_lines(listing: Listing) -> str:
    return f"{listing.company_name}: {listing.title}\n{listing.format_locations()}\n{listing.url}"


def notify(ntfy_topic: str, smtp_user: str, smtp_pass: str, email_to: list[str], listings: list[Listing]) -> None:
    """One notification per call, covering every listing passed in - callers batch by
    company so a company dumping 20 matching postings at once sends one alert, not 20."""
    if not listings:
        return
    company_name = listings[0].company_name
    if len(listings) == 1:
        listing = listings[0]
        subject = f"New {company_name} posting: {listing.title}"
        click_url = listing.url
        email_body = (
            f"Company: {company_name}\n"
            f"Role: {listing.title}\n"
            f"Location: {listing.format_locations()}\n"
            f"Apply: {listing.url}"
        )
    else:
        subject = f"{company_name}: {len(listings)} new postings"
        click_url = None
        email_body = "\n\n".join(
            f"Role: {listing.title}\nLocation: {listing.format_locations()}\nApply: {listing.url}"
            for listing in listings
        )
    shown = listings[:NTFY_MAX_LISTINGS_PER_MESSAGE]
    ntfy_body = "\n\n".join(_format_listing_lines(listing) for listing in shown)
    if len(listings) > len(shown):
        ntfy_body += f"\n\n...and {len(listings) - len(shown)} more (see email)"
    _send_both_channels(ntfy_topic, smtp_user, smtp_pass, email_to, subject, ntfy_body, email_body, click_url)


def notify_message(ntfy_topic: str, smtp_user: str, smtp_pass: str, email_to: list[str], subject: str, body: str) -> None:
    _send_both_channels(ntfy_topic, smtp_user, smtp_pass, email_to, subject, body, body)
