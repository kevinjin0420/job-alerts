from __future__ import annotations

import json
import urllib.parse
from typing import Any

from .base import Listing, fetch_url, strip_html

REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 20  # Workday's public CXS API silently 400s above this, regardless of the requested limit.
# ponytail: caps a fetch at 200 postings - fine for intern/new-grad, but a big employer's "fulltime" facet gets truncated. Raise if new postings are missed.
MAX_PAGES = 10

# Facet ids are opaque and per-tenant, so matched by descriptor text on every fetch instead of hardcoded per company.
FACET_KEYWORDS_BY_JOB_TYPE: dict[str, tuple[str, ...]] = {
    "intern": ("intern", "university"),
    "newgrad": ("college graduate", "new grad", "recent graduate"),
    # "Regular" alone covers tenants that don't say "Regular Employee" (e.g. Adobe).
    "fulltime": ("regular",),
}
# Some tenants (e.g. Workday's own site) expose no "workerSubType" facet at all - jobFamilyGroup (a "University" category) is the fallback signal there.
FACET_PARAMETER_CANDIDATES = ("workerSubType", "jobFamilyGroup")


class WorkdaySource:
    """Queries a company's public Workday CXS job-search API directly - structured JSON, same tier as GreenhouseSource/AshbySource."""

    def __init__(self, company_name: str, host: str, tenant: str, site: str, job_type: str) -> None:
        self.name = f"workday:{company_name}:{job_type}"
        self._company_name = company_name
        self._base_url = f"https://{tenant}.{host}.myworkdayjobs.com"
        self._site = site
        self._api_url = f"{self._base_url}/wday/cxs/{tenant}/{site}/jobs"
        self._job_type = job_type

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        response_body = fetch_url(
            self.name,
            self._api_url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "job-alerts-watcher"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        return json.loads(response_body)

    def _matching_facet(self) -> tuple[str, str] | None:
        """Returns (facetParameter, id) for whichever facet actually distinguishes this job_type on this tenant."""
        keywords = FACET_KEYWORDS_BY_JOB_TYPE.get(self._job_type)
        if not keywords:
            return None
        response = self._post({"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
        facets_by_parameter = {facet.get("facetParameter"): facet for facet in response.get("facets", [])}
        for parameter in FACET_PARAMETER_CANDIDATES:
            facet = facets_by_parameter.get(parameter)
            if not facet:
                continue
            for value in facet.get("values", []):
                descriptor = str(value.get("descriptor", "")).lower()
                if any(keyword in descriptor for keyword in keywords):
                    return parameter, str(value.get("id", ""))
        return None

    def fetch(self) -> list[Listing]:
        matching_facet = self._matching_facet()
        if matching_facet is None:
            return []
        facet_parameter, facet_id = matching_facet

        matches: list[Listing] = []
        total: int | None = None
        for page in range(MAX_PAGES):
            response = self._post(
                {
                    "appliedFacets": {facet_parameter: [facet_id]},
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
                        url=f"{self._base_url}/{self._site}{external_path}",
                    )
                )
            if len(postings) < PAGE_SIZE or len(matches) >= total:
                break
        return matches


def fetch_workday_description(listing_url: str) -> str | None:
    """The list API above never includes a description - only the per-job CXS detail
    endpoint does. tenant/site/external_path are all recoverable from the listing's own
    public URL (https://{tenant}.{host}.myworkdayjobs.com/{site}{external_path}) instead
    of threading extra Workday-specific state through the generic Listing type.

    Best-effort: any failure here (malformed URL, network error, missing field) just
    means this listing keeps no description, same as before this function existed -
    never worth blocking or crashing a run over."""
    try:
        parsed = urllib.parse.urlparse(listing_url)
        if not parsed.hostname:
            return None
        tenant = parsed.hostname.split(".")[0]
        path_parts = parsed.path.lstrip("/").split("/", 1)
        if len(path_parts) != 2:
            return None
        site, external_path = path_parts
        api_url = f"https://{parsed.hostname}/wday/cxs/{tenant}/{site}/{external_path}"
        body = fetch_url(
            f"workday-description:{tenant}",
            api_url,
            headers={"User-Agent": "job-alerts-watcher"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        payload = json.loads(body)
        description = payload.get("jobPostingInfo", {}).get("jobDescription", "")
        return strip_html(str(description)) or None
    except Exception:  # best-effort enrichment - a broken fetch must not block the listing
        return None
