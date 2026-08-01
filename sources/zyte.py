from __future__ import annotations

import base64
import json
import os

from .base import Listing, fetch_url, parse_rendered_html_listings

ZYTE_EXTRACT_URL = "https://api.zyte.com/v1/extract"
REQUEST_TIMEOUT_SECONDS = 60
# ponytail: lets lazy-loaded SPAs (e.g. Tesla) render before the snapshot, but only catches their first batch - raise if new postings are missed.
RENDER_WAIT_SECONDS = 8


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
        response_body = fetch_url(
            self.name,
            ZYTE_EXTRACT_URL,
            data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        payload = json.loads(response_body)
        browser_html = payload.get("browserHtml", "")
        return parse_rendered_html_listings(browser_html, self._url, self._company_name, self.name)
