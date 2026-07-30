#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from sources.base import Listing

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_TIMEOUT_SECONDS = 30

# Kept out of fit_prompt so users write only criteria - app.py exposes these via GET /api/config for an exact-prompt preview.
FIT_SYSTEM_PREAMBLE = (
    "You are screening job postings for a candidate against their fit criteria below. "
    "Answer true only if the listing clearly satisfies every criterion; if anything is "
    "unclear or unmet, answer false."
)
CRITERIA_LABEL = "Candidate's fit criteria:"
RESUME_LABEL = "Candidate resume:"
RESPONSE_INSTRUCTION = 'Respond with a JSON object: {"fits": true or false, "reason": "one short sentence explaining why"}.'
RESPONSE_INSTRUCTION_WITH_SCORE = (
    'Respond with a JSON object: {"fits": true or false, "reason": "one short sentence explaining why", '
    '"fit_score": integer from 0 to 100 rating how well the resume matches this listing}.'
)


class ClassifierError(Exception):
    pass


@dataclass(frozen=True)
class ClassificationResult:
    fits: bool
    reason: str
    fit_score: int | None = None


def _call_openrouter(
    api_key: str,
    model: str,
    system_content: str,
    user_content: str,
    properties: dict[str, object],
    required: list[str],
    max_attempts: int = 2,
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """POSTs a structured-JSON classification request; retries once by default since reasoning models occasionally return empty content. Returns (parsed content, usage)."""
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
            "max_tokens": 1000,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for _ in range(max_attempts):
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
            last_error = ClassifierError(f"Unexpected OpenRouter response shape: {payload}")
            continue

    # Wrapped, not re-raised bare: every caller (check_is_job_posting, is_good_fit)
    # is only ever built to catch ClassifierError and fail open - a bare URLError/
    # TimeoutError (e.g. a 429 from OpenRouter) would otherwise crash the whole
    # scan before it reaches any user, instead of just skipping this one listing.
    if last_error is None:
        raise ClassifierError("classifier call failed with no response")
    raise ClassifierError(f"OpenRouter call failed: {last_error}") from last_error


def check_is_job_posting(api_key: str, model: str, listing: Listing) -> tuple[bool, str]:
    """Whether this is a real job posting rather than scraped page furniture (nav
    link, footer link, cookie notice, image caption, etc.) - an objective property
    of the listing itself, the same for every user. Callers should cache the result
    per listing (see users.get_listing_validity/save_listing_validity) rather than
    recomputing it for every user who happens to see the same listing as new.
    """
    listing_text = (
        f"Company: {listing.company_name}\n"
        f"Title: {listing.title}\n"
        f"Locations: {listing.format_locations()}\n"
        f"Description: {listing.description or 'not available'}"
    )
    system_content = (
        "You are checking scraped career-page data for junk. Determine whether the given text/link is an "
        "actual job posting, as opposed to scraped page furniture (nav link, footer link, cookie notice, "
        "image caption, pagination, etc.).\n\n"
        'Respond with a JSON object: {"is_job_posting": true or false, "reason": "one short sentence explaining why"}.'
    )
    parsed, usage = _call_openrouter(
        api_key,
        model,
        system_content,
        listing_text,
        properties={"is_job_posting": {"type": "boolean"}, "reason": {"type": "string"}},
        required=["is_job_posting", "reason"],
    )
    is_job_posting = bool(parsed["is_job_posting"])
    reason = str(parsed["reason"])
    print(
        json.dumps(
            {
                "event": "validity_check",
                "model": model,
                "is_job_posting": is_job_posting,
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }
        )
    )
    return is_job_posting, reason


def build_fit_system_prompt(fit_prompt: str, resume_text: str | None = None) -> str:
    """Builds the exact system content sent to the classifier - shared with the /api/config preview so the UI can't drift from what's actually sent."""
    parts = [FIT_SYSTEM_PREAMBLE, CRITERIA_LABEL, fit_prompt.strip()]
    if resume_text:
        parts.append(f"{RESUME_LABEL}\n{resume_text}")
        parts.append(RESPONSE_INSTRUCTION_WITH_SCORE)
    else:
        parts.append(RESPONSE_INSTRUCTION)
    return "\n\n".join(parts)


def is_good_fit(
    api_key: str,
    model: str,
    fit_prompt: str,
    listing: Listing,
    resume_text: str | None = None,
    max_attempts: int = 2,
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
) -> ClassificationResult:
    listing_text = (
        f"Company: {listing.company_name}\n"
        f"Title: {listing.title}\n"
        f"Locations: {listing.format_locations()}\n"
        f"Description: {listing.description or 'not available'}"
    )

    properties: dict[str, object] = {"fits": {"type": "boolean"}, "reason": {"type": "string"}}
    required = ["fits", "reason"]

    # fit_score only makes sense when there's a resume to score the listing
    # against - without one, ask for the same fits/reason shape as always.
    if resume_text:
        properties["fit_score"] = {
            "type": "integer",
            "description": "0-100 score for how well the candidate's resume matches this listing",
        }
        required.append("fit_score")

    system_content = build_fit_system_prompt(fit_prompt, resume_text)

    parsed, usage = _call_openrouter(
        api_key, model, system_content, listing_text, properties, required, max_attempts, request_timeout_seconds
    )
    result = ClassificationResult(
        fits=bool(parsed["fits"]),
        reason=str(parsed["reason"]),
        fit_score=int(parsed["fit_score"]) if "fit_score" in parsed else None,
    )

    # JSON, not plain text: CloudWatch metric filters can only extract a
    # numeric value like input_tokens out of a structured log line.
    print(
        json.dumps(
            {
                "event": "classifier_call",
                "model": model,
                "fit": result.fits,
                "fit_score": result.fit_score,
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }
        )
    )

    return result
