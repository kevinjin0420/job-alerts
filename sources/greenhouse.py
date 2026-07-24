from __future__ import annotations

import json
import re

from .base import Listing, fetch_url

REQUEST_TIMEOUT_SECONDS = 30
INTERNSHIP_TITLE_PATTERN = re.compile(r"\bintern(s|ship)?\b", re.IGNORECASE)


class GreenhouseSource:
    """Queries a company's public Greenhouse job board API directly.

    Many companies (SpaceX, Stripe, Airbnb, Databricks, ...) publish their
    openings through Greenhouse's public boards-api, so this one class covers
    all of them: only the company name and board token differ.
    """

    def __init__(self, company_name: str, board_token: str) -> None:
        self.name = f"greenhouse:{board_token}"
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
                )
            )
        return matches
