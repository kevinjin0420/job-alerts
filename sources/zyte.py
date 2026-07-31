from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .base import Listing, looks_like_job_posting_url

ZYTE_EXTRACT_URL = "https://api.zyte.com/v1/extract"
REQUEST_TIMEOUT_SECONDS = 60
# ponytail: lets lazy-loaded SPAs (e.g. Tesla) render before the snapshot, but only catches their first batch - raise if new postings are missed.
RENDER_WAIT_SECONDS = 8
ANCHOR_PATTERN = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
HEADING_PATTERN = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
MIN_TITLE_LENGTH = 4


def _extract_anchor_title(anchor_inner_html: str) -> str:
    """Card-style SPAs (e.g. Meta) nest the title in a heading rather than as the anchor's direct text - prefer that when present."""
    heading_match = HEADING_PATTERN.search(anchor_inner_html)
    text = heading_match.group(1) if heading_match else anchor_inner_html
    return " ".join(html.unescape(TAG_PATTERN.sub(" ", text)).split())


class ZyteMisconfigured(RuntimeError):
    pass


class ZyteSource:
    """Scrapes a company's careers page via Zyte's browser-rendering API - handles anti-bot sites a plain scrape or Jina Reader can't. Costs real money per request - throttle how often callers actually fetch it."""

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"zyte:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        api_key = os.environ.get("ZYTE_API_KEY")
        if not api_key:
            raise ZyteMisconfigured("ZYTE_API_KEY is not set")

        body = json.dumps(
            {
                "url": self._url,
                "browserHtml": True,
                "actions": [{"action": "waitForTimeout", "timeout": RENDER_WAIT_SECONDS}],
            }
        ).encode("utf-8")
        auth = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
        request = urllib.request.Request(
            ZYTE_EXTRACT_URL,
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
            elapsed_ms = round((time.monotonic() - started) * 1000)
            print(f"[{self.name}] POST {ZYTE_EXTRACT_URL} for {self._url} -> {response.status} ({elapsed_ms}ms)")

        browser_html = payload.get("browserHtml", "")
        matches: list[Listing] = []
        seen_urls: set[str] = set()
        for href, inner_html in ANCHOR_PATTERN.findall(browser_html):
            title = _extract_anchor_title(inner_html)
            if len(title) < MIN_TITLE_LENGTH:
                continue
            absolute_url = urllib.parse.urljoin(self._url, href)
            if absolute_url in seen_urls or not looks_like_job_posting_url(absolute_url):
                continue
            seen_urls.add(absolute_url)
            matches.append(
                Listing(
                    source=self.name,
                    id=absolute_url,
                    company_name=self._company_name,
                    title=title,
                    locations=[],
                    url=absolute_url,
                )
            )
        return matches
