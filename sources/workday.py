from __future__ import annotations

import json
import urllib.request
from typing import Any

from .base import Listing

REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 20  # Workday's public CXS API silently 400s above this, regardless of the requested limit.
# ponytail: caps a fetch at 200 postings - fine for intern/new-grad, but a big employer's "fulltime" facet gets truncated. Raise if new postings are missed.
MAX_PAGES = 10

# Facet ids are opaque and per-tenant, so matched by descriptor text on every fetch instead of hardcoded per company.
FACET_KEYWORDS_BY_JOB_TYPE: dict[str, tuple[str, ...]] = {
    "intern": ("intern",),
    "newgrad": ("college graduate", "new grad", "recent graduate"),
    # "Regular" alone covers tenants that don't say "Regular Employee" (e.g. Adobe).
    "fulltime": ("regular",),
}


class WorkdaySource:
    """Queries a company's public Workday CXS job-search API directly - structured JSON, same tier as GreenhouseSource/AshbySource."""

    def __init__(self, company_name: str, host: str, tenant: str, site: str, job_type: str) -> None:
        self.name = f"workday:{company_name}:{job_type}"
        self._company_name = company_name
        self._base_url = f"https://{tenant}.{host}.myworkdayjobs.com"
        self._api_url = f"{self._base_url}/wday/cxs/{tenant}/{site}/jobs"
        self._job_type = job_type

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self._api_url,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "job-alerts-watcher"},
        )
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())

    def _matching_worker_sub_type_id(self) -> str | None:
        keywords = FACET_KEYWORDS_BY_JOB_TYPE.get(self._job_type)
        if not keywords:
            return None
        response = self._post({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        for facet in response.get("facets", []):
            if facet.get("facetParameter") != "workerSubType":
                continue
            for value in facet.get("values", []):
                descriptor = str(value.get("descriptor", "")).lower()
                if any(keyword in descriptor for keyword in keywords):
                    return str(value.get("id", ""))
        return None

    def fetch(self) -> list[Listing]:
        worker_sub_type_id = self._matching_worker_sub_type_id()
        if worker_sub_type_id is None:
            return []

        matches: list[Listing] = []
        total: int | None = None
        for page in range(MAX_PAGES):
            response = self._post(
                {
                    "appliedFacets": {"workerSubType": [worker_sub_type_id]},
                    "limit": PAGE_SIZE,
                    "offset": page * PAGE_SIZE,
                    "searchText": "",
                }
            )
            # Workday only reports an accurate "total" on the first page (0 on every later page).
            if total is None:
                total = int(response.get("total", 0))
            postings = response.get("jobPostings", [])
            for job in postings:
                external_path = str(job.get("externalPath", ""))
                if not external_path:
                    continue
                bullet_fields = job.get("bulletFields", [])
                job_id = str(bullet_fields[0]) if bullet_fields else external_path
                location_text = str(job.get("locationsText", ""))
                matches.append(
                    Listing(
                        source=self.name,
                        id=job_id,
                        company_name=self._company_name,
                        title=str(job.get("title", "")),
                        locations=[location_text] if location_text else [],
                        url=f"{self._base_url}{external_path}",
                    )
                )
            if len(postings) < PAGE_SIZE or len(matches) >= total:
                break
        return matches
