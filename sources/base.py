from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_JOB_ID_PATTERN = re.compile(r"[/-][A-Za-z]{0,3}\d{4,}/?(?:[?#].*)?$")
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)


def looks_like_job_posting_url(url: str) -> bool:
    """Heuristic for direct/zyte scrapers: real postings end in a numeric id, as its own path segment, a slug suffix (Tesla's style), or a letter-prefixed id glued on with no separator (ASML's "-j00348041") - nav/footer links don't."""
    return bool(_JOB_ID_PATTERN.search(url))


@dataclass(frozen=True)
class Listing:
    source: str
    id: str
    company_name: str
    title: str
    locations: list[str]
    url: str
    description: str | None = None

    @property
    def unique_id(self) -> str:
        return f"{self.source}:{self.id}"

    def format_locations(self) -> str:
        return ", ".join(self.locations) if self.locations else "Location not specified"


class Source(Protocol):
    name: str

    def fetch(self) -> list[Listing]: ...


MAX_FETCH_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_BASE_SECONDS = 2


def fetch_url(source_name: str, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    """GETs a URL, logging status/timing. Retries with backoff on a transient status (429/5xx); a hard failure (403, 404, etc.) still propagates immediately."""
    request = urllib.request.Request(url, headers=headers or {})
    for attempt in range(MAX_FETCH_ATTEMPTS):
        if attempt > 0:
            time.sleep(RETRY_BACKOFF_BASE_SECONDS * attempt)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                elapsed_ms = round((time.monotonic() - started) * 1000)
                print(f"[{source_name}] GET {url} -> {response.status} ({elapsed_ms}ms, {len(body)} bytes)")
                return body
        except urllib.error.HTTPError as error:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            is_last_attempt = attempt == MAX_FETCH_ATTEMPTS - 1
            if error.code not in RETRYABLE_STATUS_CODES or is_last_attempt:
                raise
            print(
                f"[{source_name}] GET {url} -> {error.code} ({elapsed_ms}ms), "
                f"retrying (attempt {attempt + 1}/{MAX_FETCH_ATTEMPTS})"
            )
    raise AssertionError("unreachable - loop above always returns or raises")
