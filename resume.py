from __future__ import annotations

import urllib.error
import urllib.request
from io import BytesIO

from pypdf import PdfReader

MAX_RESUME_BYTES = 5 * 1024 * 1024
RESUME_TEXT_CHAR_CAP = 6000
REQUEST_TIMEOUT_SECONDS = 15


class ResumeFetchError(Exception):
    pass


def extract_resume_text(pdf_bytes: bytes) -> str:
    """Raises ResumeFetchError with a user-facing message on any failure."""
    if len(pdf_bytes) > MAX_RESUME_BYTES:
        raise ResumeFetchError("resume must be under 5MB")
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        # "layout" mode avoids pypdf's default mode misreading kerning gaps as word breaks
        # (e.g. "Frameworks" -> "F rameworks"); whitespace-collapsing handles the rest.
        raw_text = "\n".join(page.extract_text(extraction_mode="layout") or "" for page in reader.pages)
        text = " ".join(raw_text.split())
    except Exception as error:
        raise ResumeFetchError("could not parse PDF") from error
    if not text:
        raise ResumeFetchError("no extractable text found in PDF")
    return text[:RESUME_TEXT_CHAR_CAP]


def fetch_resume_text_from_url(url: str) -> str:
    """Live-fetches and parses a PDF resume from a URL. Deliberately does no
    caching of the result - the whole point is that the user updates the file
    at this URL directly, and every caller (a real scan, a dashboard preview)
    always sees the current version without anyone re-syncing the app."""
    request = urllib.request.Request(url, headers={"User-Agent": "job-alerts"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            pdf_bytes = response.read(MAX_RESUME_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as error:
        raise ResumeFetchError(f"could not fetch url: {error}") from error
    return extract_resume_text(pdf_bytes)
