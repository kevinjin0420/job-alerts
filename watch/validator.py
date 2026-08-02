#!/usr/bin/env python3
from __future__ import annotations

import json
import sys

from llm import call_openrouter
from sources.base import Listing
from users import record_llm_call


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
        "Some sources only capture a title and link, never a description - a missing description is common "
        "and expected, not itself a sign of junk. Judge primarily on whether the title, company, and location "
        "read as a plausible, specific real job (a distinct role, not a nav label or placeholder), not on "
        "whether a description happens to be present.\n\n"
        'Respond with a JSON object: {"is_job_posting": true or false, "reason": "one short sentence explaining why"}.'
    )
    parsed, usage = call_openrouter(
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

    # Full payload/response for the LLM Logs page - kept off stdout/CloudWatch (see the
    # small print above for the metrics version). Best-effort: a DynamoDB hiccup here
    # must never fail an actual validity check.
    try:
        record_llm_call(
            event="validity_check",
            model=model,
            is_job_posting=is_job_posting,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            system_content=system_content,
            user_content=listing_text,
            reason=reason,
        )
    except Exception as error:
        print(f"record_llm_call failed: {error}", file=sys.stderr)

    return is_job_posting, reason
