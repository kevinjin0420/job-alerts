from __future__ import annotations

import json

from .base import INTERNSHIP_TITLE_PATTERN, Listing, fetch_url, strip_html

REQUEST_TIMEOUT_SECONDS = 30


class GreenhouseSource:
    """Queries a company's public Greenhouse job board API directly.

    Many companies (SpaceX, Stripe, Airbnb, Databricks, ...) publish their
    openings through Greenhouse's public boards-api, so this one class covers
    all of them: only the company name and board token differ.
    """

    def __init__(self, company_name: str, board_token: str) -> None:
        # "intern" hardcoded - this class always filters to intern-titled postings, unlike ashby/direct/zyte/workday.
        self.name = f"greenhouse:{company_name}:intern"
        self._company_name = company_name
        self._board_token = board_token

    def fetch(self) -> list[Listing]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self._board_token}/jobs"
        payload = fetch_url(
            self.name, url, headers={"User-Agent": "job-alerts-watcher"}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        parsed = json.loads(payload)
        jobs = parsed.get("jobs", []) if isinstance(parsed, dict) else []

        matches: list[Listing] = []
        for job in jobs:
            title = str(job.get("title", ""))
            if not INTERNSHIP_TITLE_PATTERN.search(title):
                continue
            job_id = str(job.get("id", ""))
            if not job_id:
                continue
            location = job.get("location", {})
            location_name = str(location.get("name", "")) if isinstance(location, dict) else ""
            matches.append(
                Listing(
                    source=self.name,
                    id=job_id,
                    company_name=self._company_name,
                    title=title,
                    locations=[location_name] if location_name else [],
                    url=str(job.get("absolute_url", "")),
                    description=self._fetch_job_content(job_id),
                )
            )
        return matches

    def _fetch_job_content(self, job_id: str) -> str | None:
        """Only called for the handful of postings that already passed the internship
        title filter above - requesting content=true on the LIST endpoint instead (every
        job on the board, not just intern-titled ones) once blew past the watch Lambda's
        memory limit: SpaceX alone has 2,102 total postings, and pulling full HTML content
        for all of them to find the 5 that are internships was a 23.8MB response."""
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{self._board_token}/jobs/{job_id}?content=true"
            body = fetch_url(self.name, url, headers={"User-Agent": "job-alerts-watcher"}, timeout=REQUEST_TIMEOUT_SECONDS)
            payload = json.loads(body)
            return strip_html(str(payload.get("content") or "")) or None
        except Exception:  # a missing description must not drop the listing
            return None
