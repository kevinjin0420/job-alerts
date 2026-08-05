from __future__ import annotations

import json
from typing import Any

from .base import Listing, fetch_url

REQUEST_TIMEOUT_SECONDS = 30
PAGE_SIZE = 50
# Not a real cap - fetch() loops until every page reported by the API's own "count" is
# consumed. This only bounds a pathological response (a corrupted/lying count) from
# looping forever; 2000 postings is far beyond anything the Technology+program filter
# below should ever return for one company.
MAX_PAGES = 40

# ByteDance's white-labeled career sites (TikTok, ByteDance itself, ...) all run the same
# underlying job-search platform and share this taxonomy - reverse-engineered via each
# site's own network calls (search/job/posts). Narrows each company's full listing (often
# 1000+ postings across every function: ops/HR/sales/research) down to the roles actually
# worth classifying.
JOB_CATEGORY_ID_TECHNOLOGY = "6704215862603155720"
SUBJECT_IDS_BACHELOR_MASTER_OR_PHD = [
    "7459985269216905480",
    "7459988146945116434",
    "7602165694751705397",
    "7602166391986194741",
    "7602165701485299973",
    "7602165694713678133",
]
RECRUITMENT_IDS_BY_JOB_TYPE = {"intern": ["202", "301"], "newgrad": ["201"]}


class ByteDancePlatformJobsSource:
    """Queries a ByteDance-family career site's own public job-search API directly -
    structured JSON, same tier as Workday/Greenhouse, and description comes bundled in
    the search response so no second per-job fetch is needed. Replaces rendering the
    search page, which only ever captured its default first page (12-50 unfiltered
    results) out of the company's full global posting list, so the actual US SWE intern
    postings were routinely never even fetched. No render cost or 4-hour cooldown, so
    this can run every watch cycle like any other structured-API source.

    Each site has an identical request/response schema but a different API host, and (per
    site) a required discriminator header - reverse-engineered per company below rather
    than guessed, since a wrong value 400s."""

    def __init__(
        self,
        company_name: str,
        job_type: str,
        *,
        source_kind: str,
        api_url: str,
        detail_url_prefix: str,
        headers: dict[str, str],
    ) -> None:
        self.name = f"{source_kind}:{company_name}:{job_type}"
        self._company_name = company_name
        self._recruitment_ids = RECRUITMENT_IDS_BY_JOB_TYPE.get(job_type)
        self._api_url = api_url
        self._detail_url_prefix = detail_url_prefix
        self._headers = headers

    def _post(self, offset: int) -> dict[str, Any]:
        body = json.dumps(
            {
                "recruitment_id_list": self._recruitment_ids,
                "job_category_id_list": [JOB_CATEGORY_ID_TECHNOLOGY],
                "subject_id_list": SUBJECT_IDS_BACHELOR_MASTER_OR_PHD,
                "location_code_list": [],
                "keyword": "",
                "limit": PAGE_SIZE,
                "offset": offset,
            }
        ).encode("utf-8")
        response_body = fetch_url(self.name, self._api_url, data=body, headers=self._headers, timeout=REQUEST_TIMEOUT_SECONDS)
        return json.loads(response_body)

    def fetch(self) -> list[Listing]:
        if self._recruitment_ids is None:
            return []
        matches: list[Listing] = []
        total: int | None = None
        for page in range(MAX_PAGES):
            payload = self._post(page * PAGE_SIZE)
            data = payload.get("data") or {}
            if total is None:
                total = int(data.get("count", 0))
            posts = data.get("job_post_list", [])
            for post in posts:
                matches.append(self._to_listing(post))
            if len(posts) < PAGE_SIZE or len(matches) >= total:
                break
        return matches

    def _to_listing(self, post: dict[str, Any]) -> Listing:
        post_id = str(post.get("id", ""))
        city = post.get("city_info") or {}
        country = city.get("parent") or {}
        while country.get("parent"):
            country = country["parent"]
        locations = [str(name) for name in (city.get("en_name"), country.get("en_name")) if name]
        # requirement carries qualifications/eligibility (e.g. "Summer of 2027" start dates)
        # that description doesn't restate - dropping it starved the classifier of the
        # clearest season signal on the posting, leaving only a title suffix to go on.
        description_parts = [str(post.get(field) or "").strip() for field in ("description", "requirement")]
        description = "\n\n".join(part for part in description_parts if part)
        return Listing(
            source=self.name,
            id=post_id,
            company_name=self._company_name,
            title=str(post.get("title", "")),
            locations=locations,
            url=f"{self._detail_url_prefix}{post_id}",
            description=description or None,
        )


# Both brands are owned by ByteDance and share the identical search API/schema - only the
# host, detail-page URL, and per-site discriminator header differ. Keyed by company name
# (not a separate source_kind each) so every brand on this platform reports its source
# health as "bytedance:{company}:{job_type}", reflecting who actually owns the site, and a
# future ByteDance-family brand only needs one new entry here.
_SITE_CONFIG_BY_COMPANY_NAME: dict[str, dict[str, Any]] = {
    "tiktok": {
        "api_url": "https://api.lifeattiktok.com/api/v1/public/supplier/search/job/posts",
        "detail_url_prefix": "https://lifeattiktok.com/search/",
        "headers": {"Content-Type": "application/json", "website-path": "tiktok", "User-Agent": "job-alerts-watcher"},
    },
    "bytedance": {
        "api_url": "https://jobs.bytedance.com/api/v1/public/supplier/search/job/posts",
        "detail_url_prefix": "https://joinbytedance.com/search/",
        "headers": {
            "Content-Type": "application/json",
            "website-path": "en",
            "x-tt-env": "boe_epam_api",
            "User-Agent": "job-alerts-watcher",
        },
    },
}


def bytedance_platform_source(company_name: str, job_type: str) -> ByteDancePlatformJobsSource | None:
    config = _SITE_CONFIG_BY_COMPANY_NAME.get(company_name.strip().lower())
    if config is None:
        return None
    return ByteDancePlatformJobsSource(company_name, job_type, source_kind="bytedance", **config)
