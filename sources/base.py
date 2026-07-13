from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Listing:
    source: str
    id: str
    company_name: str
    title: str
    locations: list[str]
    url: str

    @property
    def unique_id(self) -> str:
        return f"{self.source}:{self.id}"

    def format_locations(self) -> str:
        return ", ".join(self.locations) if self.locations else "Location not specified"


class Source(Protocol):
    name: str

    def fetch(self) -> list[Listing]: ...
