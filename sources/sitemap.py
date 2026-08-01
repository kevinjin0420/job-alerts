from __future__ import annotations

import re

from .base import INTERNSHIP_TITLE_PATTERN, Listing, fetch_url

REQUEST_TIMEOUT_SECONDS = 30
LOC_PATTERN = re.compile(r"<loc>(.*?)</loc>")
TRAILING_UUID_PATTERN = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


class SitemapSource:
    """Reads a company's public job-postings sitemap.xml directly - reliable, unauthenticated, and untouched by bot protection that blocks the actual search page (e.g. Shopify's Cloudflare-gated search). No title field exists in a sitemap, only the URL slug, so titles are approximated from it - coarser than a real API, but real current data with no anti-bot risk."""

    def __init__(self, company_name: str, sitemap_url: str) -> None:
        self.name = f"sitemap:{company_name}:intern"
        self._company_name = company_name
        self._sitemap_url = sitemap_url

    def fetch(self) -> list[Listing]:
        body = fetch_url(self.name, self._sitemap_url, headers={"User-Agent": "job-alerts-watcher"}, timeout=REQUEST_TIMEOUT_SECONDS)
        xml = body.decode("utf-8", errors="replace")

        matches: list[Listing] = []
        for url in LOC_PATTERN.findall(xml):
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            title_slug = TRAILING_UUID_PATTERN.sub("", slug).rstrip("_-")
            title = title_slug.replace("-", " ").replace("_", " ").strip().title()
            if not title or not INTERNSHIP_TITLE_PATTERN.search(title):
                continue
            matches.append(
                Listing(
                    source=self.name,
                    id=slug,
                    company_name=self._company_name,
                    title=title,
                    locations=[],
                    url=url,
                )
            )
        return matches
