from __future__ import annotations

import json
from pathlib import Path

SEEN_FILE = Path(__file__).parent / "seen.json"


def seen_file_exists() -> bool:
    return SEEN_FILE.exists()


def load_seen_ids() -> set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except (json.JSONDecodeError, ValueError):
        return set()


def save_seen_ids(seen_ids: set[str]) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen_ids), indent=2) + "\n")
