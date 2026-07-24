from __future__ import annotations

import json
import re
import urllib.parse

from .base import Listing, fetch_url

REQUEST_TIMEOUT_SECONDS = 30
HYDRATION_DATA_PATTERN = re.compile(r'window\.__staticRouterHydrationData = JSON\.parse\("(.*?)"\);', re.DOTALL)
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)
# ponytail: Apple's search does loose full-text matching (1808+ results for
# "intern", real matches scattered thin across many pages, no filter facet
# to narrow server-side) and this Lambda runs every 1 minute, so a high page
# count means sustained heavy request volume against Apple's site (risk of
# rate-limiting/blocking). Kept low for that reason; bounded best-effort
# coverage, not exhaustive - raise if it's still missing too much and the
# request volume risk is acceptable.
MAX_PAGES = 5


class AppleJobsSource:
    """Parses the search-results JSON that Apple's careers site embeds in its
    server-rendered HTML (Apple publishes no public jobs API). This depends on
    an internal page structure Apple can change without notice, so treat it as
    best-effort: if the page layout shifts, fetch() raises and the run just
    logs a per-source failure instead of blocking other sources.
    """

    name = "apple"

    def __init__(self, search_term: str = "intern") -> None:
        self._search_term = search_term

    def _fetch_page(self, page: int) -> list[dict[str, object]]:
        query = urllib.parse.urlencode({"search": self._search_term, "page": page})
        url = f"https://jobs.apple.com/en-us/search?{query}"
        html = fetch_url(self.name, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS).decode(
            "utf-8", errors="replace"
        )

        match = HYDRATION_DATA_PATTERN.search(html)
        if match is None:
            raise ValueError("Apple careers page structure has changed; hydration data not found")

        escaped_json = match.group(1)
        inner_json_string = json.loads('"' + escaped_json + '"')
        data = json.loads(inner_json_string)
        results = data.get("loaderData", {}).get("search", {}).get("searchResults", [])
        if not isinstance(results, list):
            raise ValueError("Apple careers page structure has changed; searchResults not found")
        return results

    def fetch(self) -> list[Listing]:
        matches: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            results = self._fetch_page(page)
            if not results:
                break
            for entry in results:
                title = str(entry.get("postingTitle", ""))
                if not INTERNSHIP_TITLE_PATTERN.search(title):
                    continue
                position_id = str(entry.get("positionId", ""))
                if not position_id:
                    continue
                locations_raw = entry.get("locations", [])
                locations = [
                    str(location.get("name", ""))
                    for location in locations_raw
                    if isinstance(location, dict) and location.get("name")
                ]
                matches.append(
                    Listing(
                        source=self.name,
                        id=position_id,
                        company_name="Apple",
                        title=title,
                        locations=locations,
                        url=f"https://jobs.apple.com/en-us/details/{position_id}",
                        description=str(entry.get("jobSummary")) if entry.get("jobSummary") else None,
                    )
                )
        return matches
