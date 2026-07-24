from __future__ import annotations

import json
import urllib.request

from .base import Listing

LISTINGS_URL = "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/.github/scripts/listings.json"
REQUEST_TIMEOUT_SECONDS = 30


class CommunityListSource:
    """Reads the crowd-sourced internship list vanshb03/Summer2027-Internships
    maintains, instead of scraping each company's site directly."""

    name = "community"

    def __init__(self, target_companies: list[str]) -> None:
        self._target_companies = {name.strip().lower() for name in target_companies if name.strip()}

    def fetch(self) -> list[Listing]:
        request = urllib.request.Request(LISTINGS_URL, headers={"User-Agent": "job-alerts-watcher"})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read()
        parsed = json.loads(payload)
        if not isinstance(parsed, list):
            raise ValueError("listings.json did not contain a JSON array")

        matches: list[Listing] = []
        for entry in parsed:
            company_name = str(entry.get("company_name", ""))
            if company_name.strip().lower() not in self._target_companies:
                continue
            if not entry.get("active", False) or not entry.get("is_visible", False):
                continue
            listing_id = str(entry.get("id", ""))
            if not listing_id:
                continue
            locations_raw = entry.get("locations", [])
            locations = [str(loc) for loc in locations_raw] if isinstance(locations_raw, list) else []
            matches.append(
                Listing(
                    source=self.name,
                    id=listing_id,
                    company_name=company_name,
                    title=str(entry.get("title", "Unknown role")),
                    locations=locations,
                    url=str(entry.get("url", "")),
                )
            )
        return matches
