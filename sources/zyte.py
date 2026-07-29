from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request

from .base import Listing

ZYTE_EXTRACT_URL = "https://api.zyte.com/v1/extract"
REQUEST_TIMEOUT_SECONDS = 60
ANCHOR_PATTERN = re.compile(r'<a\s+[^>]*href="([^"]+)"[^>]*>([^<]{4,})</a>', re.IGNORECASE)
MIN_TITLE_LENGTH = 4


class ZyteMisconfigured(RuntimeError):
    pass


class ZyteSource:
    """Scrapes a company's careers page through Zyte's browser-rendering API -
    real Chrome execution plus proxy/anti-bot handling, for sites (like
    Akamai-protected ones) that Jina/DirectSource can't get past.

    ponytail: same "every anchor with title-like text is a candidate posting"
    heuristic as DirectSource, applied to raw HTML anchors instead of markdown
    links since Zyte returns browserHtml, not markdown. Costs real money per
    request (unlike Jina) - callers should throttle how often this source is
    actually fetched, not run it on the same 5-minute cadence as everything
    else.
    """

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"zyte:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        api_key = os.environ.get("ZYTE_API_KEY")
        if not api_key:
            raise ZyteMisconfigured("ZYTE_API_KEY is not set")

        body = json.dumps({"url": self._url, "browserHtml": True}).encode("utf-8")
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

        html = payload.get("browserHtml", "")
        matches: list[Listing] = []
        seen_urls: set[str] = set()
        for href, title in ANCHOR_PATTERN.findall(html):
            title = title.strip()
            if len(title) < MIN_TITLE_LENGTH:
                continue
            absolute_url = urllib.parse.urljoin(self._url, href)
            if absolute_url in seen_urls:
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
