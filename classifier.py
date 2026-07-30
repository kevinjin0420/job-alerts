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
    is_job_posting: bool = True
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
        "is_job_posting": {
            "type": "boolean",
            "description": "false if this is scraped page furniture (nav link, footer link, cookie notice, "
            "image caption, etc.) rather than an actual job posting",
        },
        "fits": {"type": "boolean"},
        "reason": {"type": "string"},
    }
    required = ["is_job_posting", "fits", "reason"]
    response_instruction = (
        'Respond with a JSON object: {"is_job_posting": true or false (false if this text/link is not actually '
        'a job posting - e.g. nav/footer link, cookie notice, image caption), "fits": true or false, '
        '"reason": "one short sentence explaining why"}.'
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
            'Respond with a JSON object: {"is_job_posting": true or false (false if this text/link is not actually '
            'a job posting - e.g. nav/footer link, cookie notice, image caption), "fits": true or false, '
            '"reason": "one short sentence explaining why", '
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
            # Low reasoning effort: this is a short yes/no classification, not a task that
            # needs deep chain-of-thought. Reasoning-capable models otherwise sometimes burn
            # their whole token budget "thinking" and leave nothing for the actual JSON answer.
            "reasoning": {"effort": "low"},
            "max_tokens": 600,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    # One retry: an empty/malformed response is usually a one-off provider hiccup
    # (see the "reasoning" comment above), and retrying once avoids treating a
    # transient blip as a full classifier failure (which fails open and notifies).
    last_error: Exception | None = None
    for _ in range(2):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            continue

        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            is_job_posting = bool(parsed["is_job_posting"])
            result = ClassificationResult(
                fits=is_job_posting and bool(parsed["fits"]),
                reason=str(parsed["reason"]),
                is_job_posting=is_job_posting,
                fit_score=int(parsed["fit_score"]) if "fit_score" in parsed else None,
            )
            break
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
            last_error = ClassifierError(f"Unexpected OpenRouter response shape: {payload}")
            continue
    else:
        raise last_error if last_error else ClassifierError("classifier call failed with no response")

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
                "is_job_posting": result.is_job_posting,
                "fit_score": result.fit_score,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )
    )

    return result
