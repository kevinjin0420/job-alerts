from __future__ import annotations

import json

import boto3
from botocore.config import Config

from .base import Listing, RENDERED_DESCRIPTION_MAX_CHARS, parse_rendered_html_listings, strip_html

RENDERER_FUNCTION_NAME = "job-alerts-renderer"
# Chromium cold start + navigation can run long; give it real headroom above the renderer Lambda's own timeout.
INVOKE_READ_TIMEOUT_SECONDS = 90

_lambda_client = boto3.client("lambda", config=Config(read_timeout=INVOKE_READ_TIMEOUT_SECONDS))


class RenderError(RuntimeError):
    pass


def _render_via_lambda(url: str) -> dict[str, object]:
    """Shared by RenderSource.fetch (listing pages) and fetch_render_description
    (individual job pages) - same renderer Lambda, just a different target URL."""
    response = _lambda_client.invoke(
        FunctionName=RENDERER_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps({"url": url}).encode("utf-8"),
    )
    payload = json.loads(response["Payload"].read())
    if response.get("FunctionError"):
        raise RenderError(payload.get("errorMessage", "renderer failed"))
    return payload


class RenderSource:
    """Renders a company's careers page via our own headless-Chromium Lambda - same job as ZyteSource, no anti-bot capability, effectively free."""

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"renderer:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        payload = _render_via_lambda(self._url)
        return parse_rendered_html_listings(payload["html"], self._url, self._company_name, self.name)


def fetch_render_description(url: str) -> str | None:
    """Only called for listings that already need a description (see
    watch.resolve_listing_descriptions) - the renderer has no structured description field
    like Workday/Greenhouse/Amazon/Oracle's APIs, only the full rendered page, so this is
    the whole detail page stripped to text (nav/footer included, not just the posting) and
    capped at RENDERED_DESCRIPTION_MAX_CHARS."""
    try:
        payload = _render_via_lambda(url)
        return strip_html(str(payload["html"]))[:RENDERED_DESCRIPTION_MAX_CHARS] or None
    except Exception:  # a missing description must not drop the listing
        return None
