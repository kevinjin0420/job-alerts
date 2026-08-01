#!/usr/bin/env python3
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Kept short so 10 retries stays well under the watch Lambda's timeout.
REQUEST_TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 10
RETRY_BACKOFF_BASE_SECONDS = 1


class LLMCallError(Exception):
    """Raised by both the validator (check_is_job_posting) and the classifier (is_good_fit) - this module has no opinion on which one is calling it."""

    pass


def call_openrouter(
    api_key: str,
    model: str,
    system_content: str,
    user_content: str,
    properties: dict[str, object],
    required: list[str],
    max_attempts: int = MAX_ATTEMPTS,
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """POSTs a structured-JSON completion request; retries with increasing backoff, since reasoning models occasionally return empty/malformed content. Returns (parsed content, usage)."""
    body = json.dumps(
        {
            "model": model,
            "messages": [
                # Some providers (e.g. Alibaba/Qwen) reject json_schema response_format
                # unless the word "json" literally appears in the messages.
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "classification",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            },
            # A hard token cap, not "effort": "low" - some models (e.g. qwen3.6-flash)
            # ignore effort and reason at length regardless, blowing through max_tokens
            # before ever emitting the JSON content and returning empty/malformed
            # output on every call - a systematic failure, not the rare transient one
            # the retry above exists for, so every listing was failing open and
            # getting notified regardless of fit. max_tokens leaves headroom above
            # the reasoning cap for the actual JSON content.
            "reasoning": {"max_tokens": 150},
            # Some OpenRouter backends don't cleanly cap reasoning at the hint above, truncating the JSON reason mid-word - 4000 gives real headroom.
            "max_tokens": 4000,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(max_attempts):
        if attempt > 0:
            time.sleep(RETRY_BACKOFF_BASE_SECONDS * attempt)
        try:
            with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            continue

        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            for key in required:
                if key not in parsed:
                    raise KeyError(key)
            return parsed, payload.get("usage", {})
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            last_error = LLMCallError(f"Unexpected OpenRouter response shape: {payload}")
            continue

    # Wrapped, not re-raised bare: every caller catches LLMCallError specifically (check_is_job_posting fails open, is_good_fit fails closed) - a bare URLError/TimeoutError would otherwise crash the whole scan instead of just skipping this one listing.
    if last_error is None:
        raise LLMCallError("LLM call failed with no response")
    raise LLMCallError(f"OpenRouter call failed: {last_error}") from last_error
