from __future__ import annotations

import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_JOB_ID_PATTERN = re.compile(r"/\d{4,}/?(?:[?#].*)?$")


def looks_like_job_posting_url(url: str) -> bool:
    """Heuristic for direct/zyte scrapers: real ATS postings almost always end in
    a numeric job id (e.g. /positions/7732569/), while nav/footer/social links don't.
    ponytail: imperfect (a few non-job pages coincidentally end in a number too),
    the classifier downstream still filters whatever slips through this.
    """
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


def fetch_url(source_name: str, url: str, *, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    """GETs a URL, logging status/timing for request-level debugging.

    HTTPError (the shape anti-bot blocks usually take, e.g. 403/429) is left
    to propagate with urllib's own descriptive message rather than caught
    here - the caller's per-source failure log already surfaces it.
    """
    request = urllib.request.Request(url, headers=headers or {})
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        elapsed_ms = round((time.monotonic() - started) * 1000)
        print(f"[{source_name}] GET {url} -> {response.status} ({elapsed_ms}ms, {len(body)} bytes)")
        return body
