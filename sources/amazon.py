from __future__ import annotations

import json
import urllib.parse

from .base import Listing, fetch_url

SEARCH_URL = "https://www.amazon.jobs/en/search.json"
REQUEST_TIMEOUT_SECONDS = 30
RESULT_LIMIT = 100

# No keyword maps cleanly to "fulltime" at Amazon's size, so it's deliberately absent - build_job_type_sources then skips it.
QUERY_BY_JOB_TYPE = {
    "intern": "intern",
    "newgrad": "early career",
}


class AmazonJobsSource:
    """Queries Amazon's public jobs search API (amazon.jobs/en/search.json)
    directly - structured JSON, same tier as GreenhouseSource."""

    def __init__(self, company_name: str, job_type: str) -> None:
        self.name = f"amazon:{company_name}:{job_type}"
        self._company_name = company_name
        self._job_type = job_type

    def fetch(self) -> list[Listing]:
        query = QUERY_BY_JOB_TYPE.get(self._job_type)
        if query is None:
            return []

        url = f"{SEARCH_URL}?base_query={urllib.parse.quote(query)}&result_limit={RESULT_LIMIT}&offset=0"
        body = fetch_url(self.name, url, headers={"User-Agent": "job-alerts-watcher"}, timeout=REQUEST_TIMEOUT_SECONDS)
        payload = json.loads(body)

        matches: list[Listing] = []
        for job in payload.get("jobs", []):
            job_id = str(job.get("id_icims", ""))
            job_path = str(job.get("job_path", ""))
            if not job_id or not job_path:
                continue
            location = str(job.get("normalized_location") or job.get("location") or "")
            matches.append(
                Listing(
                    source=self.name,
                    id=job_id,
                    company_name=self._company_name,
                    title=str(job.get("title", "")),
                    locations=[location] if location else [],
                    url=f"https://www.amazon.jobs{job_path}",
                )
            )
        return matches
