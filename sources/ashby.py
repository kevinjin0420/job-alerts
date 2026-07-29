from __future__ import annotations

import json

from .base import Listing, fetch_url

ASHBY_API_URL = "https://api.ashbyhq.com/posting-api/job-board/{board_name}"
REQUEST_TIMEOUT_SECONDS = 30
EMPLOYMENT_TYPE_BY_JOB_TYPE = {"intern": "Intern", "fulltime": "FullTime"}
# ponytail: Ashby's schema has no distinct "new grad" employment type, only
# Intern/FullTime/PartTime/Contract/Temporary - new-grad roles are just
# FullTime with the level implied by title/description. "newgrad" falls back
# to all FullTime postings; the classifier is what actually separates
# new-grad from senior roles.


class AshbySource:
    """Queries a company's public Ashby job-board API directly - structured
    JSON, no scraping needed, same tier as GreenhouseSource."""

    def __init__(self, company_name: str, board_name: str, job_type: str) -> None:
        self.name = f"ashby:{board_name}:{job_type}"
        self._company_name = company_name
        self._board_name = board_name
        self._job_type = job_type

    def fetch(self) -> list[Listing]:
        url = ASHBY_API_URL.format(board_name=self._board_name)
        payload = fetch_url(self.name, url, headers={"User-Agent": "job-alerts-watcher"}, timeout=REQUEST_TIMEOUT_SECONDS)
        parsed = json.loads(payload)
        jobs = parsed.get("jobs", []) if isinstance(parsed, dict) else []

        wanted_employment_type = EMPLOYMENT_TYPE_BY_JOB_TYPE.get(self._job_type, "FullTime")
        matches: list[Listing] = []
        for job in jobs:
            if job.get("employmentType") != wanted_employment_type or not job.get("isListed", True):
                continue
            job_id = str(job.get("id", ""))
            if not job_id:
                continue
            location = str(job.get("location", ""))
            matches.append(
                Listing(
                    source=self.name,
                    id=job_id,
                    company_name=self._company_name,
                    title=str(job.get("title", "")),
                    locations=[location] if location else [],
                    url=str(job.get("jobUrl", "")),
                    description=job.get("descriptionPlain") or None,
                )
            )
        return matches
