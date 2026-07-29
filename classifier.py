#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from sources.base import Listing

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30


class ClassifierError(Exception):
    pass


@dataclass(frozen=True)
class ClassificationResult:
    fits: bool
    reason: str
    fit_score: int | None = None


def is_good_fit(
    api_key: str, model: str, fit_prompt: str, listing: Listing, resume_text: str | None = None
) -> ClassificationResult:
    listing_text = (
        f"Company: {listing.company_name}\n"
        f"Title: {listing.title}\n"
        f"Locations: {listing.format_locations()}\n"
        f"Description: {listing.description or 'not available'}"
    )

    properties: dict[str, object] = {
        "fits": {"type": "boolean"},
        "reason": {"type": "string"},
    }
    required = ["fits", "reason"]
    response_instruction = (
        'Respond with a JSON object: {"fits": true or false, "reason": "one short sentence explaining why"}.'
    )
    system_content = f"{fit_prompt}\n\n{response_instruction}"

    # fit_score only makes sense when there's a resume to score the listing
    # against - without one, ask for the same fits/reason shape as always.
    if resume_text:
        properties["fit_score"] = {
            "type": "integer",
            "description": "0-100 score for how well the candidate's resume matches this listing",
        }
        required.append("fit_score")
        response_instruction = (
            'Respond with a JSON object: {"fits": true or false, "reason": "one short sentence explaining why", '
            '"fit_score": integer from 0 to 100 rating how well the resume matches this listing}.'
        )
        system_content = f"{fit_prompt}\n\nCandidate resume:\n{resume_text}\n\n{response_instruction}"

    body = json.dumps(
        {
            "model": model,
            "messages": [
                # Some providers (e.g. Alibaba/Qwen) reject json_schema response_format
                # unless the word "json" literally appears in the messages.
                {"role": "system", "content": system_content},
                {"role": "user", "content": listing_text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "fit_decision",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                        "additionalProperties": False,
                    },
                },
            },
            "max_tokens": 200,
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
        parsed = json.loads(content)
        result = ClassificationResult(
            fits=bool(parsed["fits"]),
            reason=str(parsed["reason"]),
            fit_score=int(parsed["fit_score"]) if "fit_score" in parsed else None,
        )
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
                "fit": result.fits,
                "fit_score": result.fit_score,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
    )

    return result
