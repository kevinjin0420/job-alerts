#!/usr/bin/env python3
from __future__ import annotations

import json
from dataclasses import dataclass

from llm import MAX_ATTEMPTS, REQUEST_TIMEOUT_SECONDS, call_openrouter
from sources.base import Listing

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


@dataclass(frozen=True)
class ClassificationResult:
    fits: bool
    reason: str
    fit_score: int | None = None


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
    max_attempts: int = MAX_ATTEMPTS,
    request_timeout_seconds: int = REQUEST_TIMEOUT_SECONDS,
    user_id: str | None = None,
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
            "minimum": 0,
            "maximum": 100,
            "description": "0-100 score for how well the candidate's resume matches this listing",
        }
        required.append("fit_score")

    system_content = build_fit_system_prompt(fit_prompt, resume_text)

    parsed, usage = call_openrouter(
        api_key, model, system_content, listing_text, properties, required, max_attempts, request_timeout_seconds
    )
    # schema minimum/maximum is a hint, not a guarantee - a model returned a stray year (2022) as the score once, so it's clamped here too.
    raw_fit_score = int(parsed["fit_score"]) if "fit_score" in parsed else None
    result = ClassificationResult(
        fits=bool(parsed["fits"]),
        reason=str(parsed["reason"]),
        fit_score=max(0, min(100, raw_fit_score)) if raw_fit_score is not None else None,
    )

    # JSON, not plain text: CloudWatch metric filters can only extract a numeric value like input_tokens out of a structured log line.
    print(
        json.dumps(
            {
                "event": "classifier_call",
                "model": model,
                "user_id": user_id,
                "fit": result.fits,
                "fit_score": result.fit_score,
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }
        )
    )

    return result
