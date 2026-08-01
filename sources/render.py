from __future__ import annotations

import json

import boto3
from botocore.config import Config

from .base import Listing, parse_rendered_html_listings

RENDERER_FUNCTION_NAME = "job-alerts-renderer"
# Chromium cold start + navigation can run long; give it real headroom above the renderer Lambda's own timeout.
INVOKE_READ_TIMEOUT_SECONDS = 90

_lambda_client = boto3.client("lambda", config=Config(read_timeout=INVOKE_READ_TIMEOUT_SECONDS))


class RenderError(RuntimeError):
    pass


class RenderSource:
    """Renders a company's careers page via our own headless-Chromium Lambda - same job as ZyteSource, no anti-bot capability, effectively free."""

    def __init__(self, company_name: str, url: str, job_type: str) -> None:
        self.name = f"renderer:{company_name}:{job_type}"
        self._company_name = company_name
        self._url = url

    def fetch(self) -> list[Listing]:
        response = _lambda_client.invoke(
            FunctionName=RENDERER_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps({"url": self._url}).encode("utf-8"),
        )
        payload = json.loads(response["Payload"].read())
        if response.get("FunctionError"):
            raise RenderError(payload.get("errorMessage", "renderer failed"))
        return parse_rendered_html_listings(payload["html"], self._url, self._company_name, self.name)
