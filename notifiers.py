from __future__ import annotations

import smtplib
import urllib.error
import urllib.request
from email.mime.text import MIMEText

from sources.base import Listing

REQUEST_TIMEOUT_SECONDS = 30
NotificationError = (urllib.error.URLError, smtplib.SMTPException, OSError)


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


def notify(ntfy_topic: str, smtp_user: str, smtp_pass: str, email_to: list[str], listing: Listing) -> None:
    send_ntfy_message(
        ntfy_topic,
        f"New {listing.company_name} internship",
        f"{listing.company_name}: {listing.title}\n{listing.format_locations()}\n{listing.url}",
        click_url=listing.url,
    )
    send_email_message(
        smtp_user,
        smtp_pass,
        email_to,
        f"New {listing.company_name} internship: {listing.title}",
        f"Company: {listing.company_name}\n"
        f"Role: {listing.title}\n"
        f"Location: {listing.format_locations()}\n"
        f"Apply: {listing.url}",
    )


def notify_message(ntfy_topic: str, smtp_user: str, smtp_pass: str, email_to: list[str], subject: str, body: str) -> None:
    send_ntfy_message(ntfy_topic, subject, body)
    send_email_message(smtp_user, smtp_pass, email_to, subject, body)
