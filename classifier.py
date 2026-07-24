#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request

from sources.base import Listing

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30


class ClassifierError(Exception):
    pass


def is_good_fit(api_key: str, model: str, fit_prompt: str, listing: Listing) -> bool:
    listing_text = (
        f"Company: {listing.company_name}\n"
        f"Title: {listing.title}\n"
        f"Locations: {listing.format_locations()}\n"
        f"Description: {listing.description or 'not available'}"
    )
    body = json.dumps(
        {
            "model": model,
            "messages": [
                # Some providers (e.g. Alibaba/Qwen) reject json_schema response_format
                # unless the word "json" literally appears in the messages.
                {"role": "system", "content": f'{fit_prompt}\n\nRespond with a JSON object: {{"fits": true or false}}.'},
                {"role": "user", "content": listing_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fit_decision",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"fits": {"type": "boolean"}},
                        "required": ["fits"],
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": 20,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError) as error:
        raise ClassifierError(str(error)) from error

    try:
        content = payload["choices"][0]["message"]["content"]
        fits = bool(json.loads(content)["fits"])
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise ClassifierError(f"Unexpected OpenRouter response shape: {payload}") from error

    usage = payload.get("usage", {})
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    # JSON, not plain text: CloudWatch metric filters can only extract a
    # numeric value like input_tokens out of a structured log line.
    print(
        json.dumps(
            {
                "event": "classifier_call",
                "model": model,
                "fit": fits,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
    )

    return fits
