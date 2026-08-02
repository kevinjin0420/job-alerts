from __future__ import annotations

import json
import urllib.parse

from .base import INTERNSHIP_TITLE_PATTERN, Listing, fetch_url, strip_html

REQUISITIONS_URL = "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
JOB_URL_TEMPLATE = "https://careers.oracle.com/jobs/#en/sites/jobsearch/job/{id}"
REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 50
# ponytail: Oracle's full-text search for "intern" also matches unrelated senior roles (e.g. "Internal Audit"), filtered client-side by title regex - bounded page count trades off against sustained request volume, same as AppleJobsSource. Raise if postings are still missed.
MAX_PAGES = 6


class OracleSource:
    """Queries Oracle's public Recruiting Cloud API directly - structured JSON, but full-text search only (no clean job-type facet), so this only supports "intern"."""

    def __init__(self, company_name: str) -> None:
        self.name = f"oracle:{company_name}:intern"
        self._company_name = company_name

    def _fetch_page(self, page: int) -> list[dict[str, object]]:
        finder = f"findReqs;siteNumber=CX_1,limit={PAGE_SIZE},offset={page * PAGE_SIZE},keyword=intern"
        query = urllib.parse.urlencode({"onlyData": "true", "expand": "requisitionList", "finder": finder})
        body = fetch_url(
            self.name,
            f"{REQUISITIONS_URL}?{query}",
            headers={"User-Agent": "job-alerts-watcher"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        payload = json.loads(body)
        items = payload.get("items", [])
        return items[0].get("requisitionList", []) if items else []

    def fetch(self) -> list[Listing]:
        matches: list[Listing] = []
        seen_ids: set[str] = set()
        for page in range(MAX_PAGES):
            requisitions = self._fetch_page(page)
            if not requisitions:
                break
            for req in requisitions:
                title = str(req.get("Title", ""))
                if not INTERNSHIP_TITLE_PATTERN.search(title):
                    continue
                req_id = str(req.get("Id", ""))
                if not req_id or req_id in seen_ids:
                    continue
                seen_ids.add(req_id)
                location = str(req.get("PrimaryLocation", ""))
                description = str(req.get("ShortDescriptionStr") or "")
                matches.append(
                    Listing(
                        source=self.name,
                        id=req_id,
                        company_name=self._company_name,
                        title=title,
                        locations=[location] if location else [],
                        url=JOB_URL_TEMPLATE.format(id=req_id),
                        description=strip_html(description) or None,
                    )
                )
        return matches
