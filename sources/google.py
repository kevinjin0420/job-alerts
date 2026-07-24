from __future__ import annotations

import json
import re
import urllib.parse

from .base import Listing, fetch_url

REQUEST_TIMEOUT_SECONDS = 30
RESULTS_PATTERN = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(\[.*?\]), sideChannel", re.DOTALL)
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)
PAGE_SIZE = 20
# ponytail: currently ~20 total Google intern postings fit on page 1 (page 2
# already comes back empty), but bound pagination anyway in case that grows.
MAX_PAGES = 5


class GoogleJobsSource:
    """Parses the search-results JSON Google's careers site embeds in its
    server-rendered HTML as an AF_initDataCallback positional array (Google
    publishes no public jobs API). More brittle than Apple's keyed JSON since
    field meaning depends on array position, not a key - if Google reshuffles
    the array, fetch() raises and the run just logs a per-source failure
    instead of blocking other sources.
    """

    name = "google"

    def _fetch_page(self, page: int) -> list[list[object]]:
        query = urllib.parse.urlencode({"employment_type": "INTERN", "page": page})
        url = f"https://www.google.com/about/careers/applications/jobs/results?{query}"
        html = fetch_url(self.name, url, headers={"User-Agent": "Mozilla/5.0"}, timeout=REQUEST_TIMEOUT_SECONDS).decode(
            "utf-8", errors="replace"
        )
        match = RESULTS_PATTERN.search(html)
        if match is None:
            raise ValueError("Google careers page structure has changed; ds:1 data block not found")
        data = json.loads(match.group(1))
        jobs = data[0] if data and isinstance(data[0], list) else []
        return jobs

    def fetch(self) -> list[Listing]:
        matches: list[Listing] = []
        for page in range(1, MAX_PAGES + 1):
            jobs = self._fetch_page(page)
            if not jobs:
                break
            for job in jobs:
                try:
                    job_id = str(job[0])
                    title = str(job[1])
                    apply_url = str(job[2])
                    locations_raw = job[9]
                except (IndexError, TypeError) as error:
                    raise ValueError(
                        "Google careers page structure has changed; unexpected job entry shape"
                    ) from error
                if not INTERNSHIP_TITLE_PATTERN.search(title):
                    continue
                if not job_id:
                    continue
                locations = [str(loc[0]) for loc in locations_raw if isinstance(loc, list) and loc] if isinstance(
                    locations_raw, list
                ) else []
                description_parts = [
                    str(field[1])
                    for field in (job[3], job[4])
                    if isinstance(field, list) and len(field) > 1 and field[1]
                ]
                matches.append(
                    Listing(
                        source=self.name,
                        id=job_id,
                        company_name="Google",
                        title=title,
                        locations=locations,
                        url=apply_url,
                        description="\n\n".join(description_parts) if description_parts else None,
                    )
                )
            if len(jobs) < PAGE_SIZE:
                break
        return matches
