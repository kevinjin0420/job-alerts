from __future__ import annotations

import re

from .base import Listing, fetch_url, looks_like_job_posting_url

JINA_READER_URL = "https://r.jina.ai/"
REQUEST_TIMEOUT_SECONDS = 30
MARKDOWN_LINK_PATTERN = re.compile(r"(?<!!)\[([^\]]{4,})\]\((https?://[^\s\)]+)\)")
MIN_TITLE_LENGTH = 4


class DirectSource:
    """Scrapes a company's own careers page (already filtered to one job
    type via its URL, e.g. "?type=intern") through Jina's free Reader API,
    which renders JS and returns clean markdown - covers sites we can't
    parse with a plain HTTP GET, without needing our own headless browser.

    ponytail: "every markdown link with title-like text and a numeric job id
    in its URL is a candidate posting" - a generic heuristic, not a real
    per-site parser. Filters most nav/footer noise via looks_like_job_posting_url;
    the classifier downstream still filters whatever slips through. Upgrade to
    a site-specific parser if this heuristic misses real listings or produces
    too much noise once tested against real target companies.
    """

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"direct:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        markdown = fetch_url(
            self.name,
            f"{JINA_READER_URL}{self._url}",
            headers={"User-Agent": "job-alerts-watcher"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        ).decode("utf-8", errors="replace")

        matches: list[Listing] = []
        seen_urls: set[str] = set()
        for title, link in MARKDOWN_LINK_PATTERN.findall(markdown):
            title = title.strip()
            if len(title) < MIN_TITLE_LENGTH or link in seen_urls or not looks_like_job_posting_url(link):
                continue
            seen_urls.add(link)
            matches.append(
                Listing(
                    source=self.name,
                    id=link,
                    company_name=self._company_name,
                    title=title,
                    locations=[],
                    url=link,
                )
            )
        return matches
