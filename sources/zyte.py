from __future__ import annotations

import base64
import json
import os

from .base import Listing, RENDERED_DESCRIPTION_MAX_CHARS, fetch_url, parse_rendered_html_listings, strip_html

ZYTE_EXTRACT_URL = "https://api.zyte.com/v1/extract"
REQUEST_TIMEOUT_SECONDS = 60
# ponytail: lets lazy-loaded SPAs (e.g. Tesla) render before the snapshot, but only catches their first batch - raise if new postings are missed.
RENDER_WAIT_SECONDS = 8


class ZyteMisconfigured(RuntimeError):
    pass


def _render_via_zyte(source_name: str, url: str) -> str:
    """Shared by ZyteSource.fetch (listing pages) and fetch_zyte_description (individual
    job pages) - same paid render API, just a different target URL."""
    api_key = os.environ.get("ZYTE_API_KEY")
    if not api_key:
        raise ZyteMisconfigured("ZYTE_API_KEY is not set")

    body = json.dumps(
        {
            "url": url,
            "browserHtml": True,
            "actions": [{"action": "waitForTimeout", "timeout": RENDER_WAIT_SECONDS}],
        }
    ).encode("utf-8")
    auth = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
    response_body = fetch_url(
        source_name,
        ZYTE_EXTRACT_URL,
        data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    payload = json.loads(response_body)
    return str(payload.get("browserHtml", ""))


class ZyteSource:
    """Scrapes a company's careers page via Zyte's browser-rendering API - handles anti-bot sites a plain scrape or Jina Reader can't. Costs real money per request - throttle how often callers actually fetch it."""

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"zyte:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        browser_html = _render_via_zyte(self.name, self._url)
        return parse_rendered_html_listings(browser_html, self._url, self._company_name, self.name)


def fetch_zyte_description(url: str) -> str | None:
    """Only called for listings that already need a description (see
    watch.resolve_listing_descriptions) - Zyte has no structured description field like
    Workday/Greenhouse/Amazon/Oracle's APIs, only the full rendered page, so this is the
    whole detail page stripped to text (nav/footer included, not just the posting) and
    capped at RENDERED_DESCRIPTION_MAX_CHARS. Real Zyte cost per call - only exists because
    the listing already passed every other new/needs-classifying filter first."""
    try:
        browser_html = _render_via_zyte(f"zyte-description:{url}", url)
        return strip_html(browser_html)[:RENDERED_DESCRIPTION_MAX_CHARS] or None
    except Exception:  # a missing description must not drop the listing
        return None
