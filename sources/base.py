from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol

_JOB_ID_PATTERN = re.compile(r"[/-][A-Za-z]{0,3}\d{4,}/?(?:[?#].*)?$")
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)
_ANCHOR_PATTERN = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_HEADING_PATTERN = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_MIN_TITLE_LENGTH = 4


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


def _extract_anchor_title(anchor_inner_html: str) -> str:
    """Card-style SPAs (e.g. Meta) nest the title in a heading rather than as the anchor's direct text - prefer that when present."""
    heading_match = _HEADING_PATTERN.search(anchor_inner_html)
    text = heading_match.group(1) if heading_match else anchor_inner_html
    return " ".join(html.unescape(_TAG_PATTERN.sub(" ", text)).split())


def parse_rendered_html_listings(rendered_html: str, base_url: str, company_name: str, source_name: str) -> list[Listing]:
    """Extracts job-posting anchors out of a rendered page (Zyte or the self-hosted renderer both return full post-JS HTML) - shared so both sources parse identically."""
    matches: list[Listing] = []
    seen_urls: set[str] = set()
    for href, inner_html in _ANCHOR_PATTERN.findall(rendered_html):
        title = _extract_anchor_title(inner_html)
        if len(title) < _MIN_TITLE_LENGTH:
            continue
        absolute_url = urllib.parse.urljoin(base_url, href)
        if absolute_url in seen_urls or not looks_like_job_posting_url(absolute_url):
            continue
        seen_urls.add(absolute_url)
        matches.append(
            Listing(
                source=source_name,
                id=absolute_url,
                company_name=company_name,
                title=title,
                locations=[],
                url=absolute_url,
            )
        )
    return matches


class Source(Protocol):
    name: str

    def fetch(self) -> list[Listing]: ...


MAX_FETCH_ATTEMPTS = 3
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRY_BACKOFF_BASE_SECONDS = 2


def fetch_url(
    source_name: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    data: bytes | None = None,
) -> bytes:
    """GETs (or POSTs, when data is given - urllib implies POST from a non-None body) a URL, logging status/timing. Retries with backoff on a transient status (429/5xx) or a connection-level failure (timeout, DNS, reset); a hard failure (403, 404, etc.) still propagates immediately."""
    request = urllib.request.Request(url, data=data, headers=headers or {})
    method = request.get_method()
    for attempt in range(MAX_FETCH_ATTEMPTS):
        if attempt > 0:
            time.sleep(RETRY_BACKOFF_BASE_SECONDS * attempt)
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                elapsed_ms = round((time.monotonic() - started) * 1000)
                print(f"[{source_name}] {method} {url} -> {response.status} ({elapsed_ms}ms, {len(body)} bytes)")
                return body
        except urllib.error.HTTPError as error:
            elapsed_ms = round((time.monotonic() - started) * 1000)
            is_last_attempt = attempt == MAX_FETCH_ATTEMPTS - 1
            if error.code not in RETRYABLE_STATUS_CODES or is_last_attempt:
                raise
            print(
                f"[{source_name}] {method} {url} -> {error.code} ({elapsed_ms}ms), "
                f"retrying (attempt {attempt + 1}/{MAX_FETCH_ATTEMPTS})"
            )
        except (TimeoutError, urllib.error.URLError) as error:
            # Not an HTTPError - no status code to gate on, but a timeout/DNS-blip/reset
            # is exactly as transient as a 429/5xx, so it gets the same retry budget
            # instead of failing on the very first attempt (HTTPError is a URLError
            # subclass, so this branch never shadows the more specific one above).
            elapsed_ms = round((time.monotonic() - started) * 1000)
            is_last_attempt = attempt == MAX_FETCH_ATTEMPTS - 1
            if is_last_attempt:
                raise
            print(
                f"[{source_name}] {method} {url} -> {error} ({elapsed_ms}ms), "
                f"retrying (attempt {attempt + 1}/{MAX_FETCH_ATTEMPTS})"
            )
    raise AssertionError("unreachable - loop above always returns or raises")
