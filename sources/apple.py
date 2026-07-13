from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request

from .base import Listing

REQUEST_TIMEOUT_SECONDS = 30
HYDRATION_DATA_PATTERN = re.compile(r'window\.__staticRouterHydrationData = JSON\.parse\("(.*?)"\);', re.DOTALL)
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)


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

    def fetch(self) -> list[Listing]:
        query = urllib.parse.urlencode({"search": self._search_term})
        url = f"https://jobs.apple.com/en-us/search?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            html = response.read().decode("utf-8", errors="replace")

        match = HYDRATION_DATA_PATTERN.search(html)
        if match is None:
            raise ValueError("Apple careers page structure has changed; hydration data not found")

        escaped_json = match.group(1)
        inner_json_string = json.loads('"' + escaped_json + '"')
        data = json.loads(inner_json_string)
        results = data.get("loaderData", {}).get("search", {}).get("searchResults", [])
        if not isinstance(results, list):
            raise ValueError("Apple careers page structure has changed; searchResults not found")

        matches: list[Listing] = []
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
                )
            )
        return matches
