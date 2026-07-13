from __future__ import annotations

from .apple import AppleJobsSource
from .base import Listing, Source
from .community import CommunityListSource
from .greenhouse import GreenhouseSource

__all__ = ["Listing", "Source", "build_sources"]


def build_sources(enabled_source_specs: list[str], community_companies: list[str]) -> list[Source]:
    """Turns ENABLED_SOURCES spec strings into Source instances.

    Spec formats:
      - "community"                          -> crowd-sourced list, filtered to COMPANIES
      - "greenhouse:<CompanyName>:<token>"   -> direct Greenhouse boards-api query
      - "apple"                              -> Apple careers page scrape

    Add a new kind by writing a class with a `name` attribute and a
    `fetch() -> list[Listing]` method, then registering its spec prefix here.
    """
    sources: list[Source] = []
    for spec in enabled_source_specs:
        parts = spec.split(":")
        kind = parts[0]
        if kind == "community":
            sources.append(CommunityListSource(community_companies))
        elif kind == "greenhouse":
            if len(parts) != 3:
                raise ValueError(
                    f"greenhouse source spec must be 'greenhouse:<CompanyName>:<board_token>', got: {spec!r}"
                )
            _, company_name, board_token = parts
            sources.append(GreenhouseSource(company_name, board_token))
        elif kind == "apple":
            sources.append(AppleJobsSource())
        else:
            raise ValueError(f"Unknown source kind: {kind!r}")
    return sources
