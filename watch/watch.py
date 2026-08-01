#!/usr/bin/env python3
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
from typing import Any

import boto3

from classifier import MAX_ATTEMPTS as CLASSIFIER_MAX_ATTEMPTS
from classifier import ClassificationResult, is_good_fit
from llm import LLMCallError
from notifiers import NotificationError, notify, notify_message
from resume import ResumeFetchError, fetch_resume_text_from_url
from sources import Listing, Source, build_sources
from sources.amazon import QUERY_BY_JOB_TYPE as AMAZON_QUERY_BY_JOB_TYPE
from sources.amazon import AmazonJobsSource
from sources.ashby import EMPLOYMENT_TYPE_BY_JOB_TYPE, AshbySource
from sources.oracle import OracleSource
from sources.render import RenderSource
from sources.sitemap import SitemapSource
from sources.workday import WorkdaySource
from sources.zyte import ZyteSource
from users import (
    get_listing_validity,
    get_llm_model,
    get_source_last_success,
    is_source_alerted,
    list_active_users,
    list_all_users,
    list_companies,
    load_seen_ids,
    load_user_config,
    load_user_profile,
    mark_source_alerted,
    record_listings,
    record_source_failure,
    record_source_success,
    save_listing_validity,
)
from validator import check_is_job_posting

DEFAULT_JOB_TYPES = ["intern"]
SOURCE_FAILURE_ALERT_THRESHOLD = 3
CLASSIFIER_HEALTH_KEY = "classifier:openrouter"
# Same source-health table/threshold used for scraper sources and the classifier -
# a Lambda "failing" here means it logged Errors in its own recent CloudWatch metrics,
# checked once per watch run rather than via a separate CloudWatch Alarm/SNS topic.
LAMBDA_HEALTH_FUNCTION_NAMES = {"lambda:dashboard": "job-alerts-dashboard", "lambda:renderer": "job-alerts-renderer"}
LAMBDA_HEALTH_CHECK_WINDOW_MINUTES = 15
cloudwatch_client = boto3.client("cloudwatch")
JOB_TYPE_URL_FIELDS = {"intern": "intern_url", "newgrad": "newgrad_url", "fulltime": "fulltime_url"}
# Shared by zyte and render - both render a page via a real browser; the cooldown avoids hammering
# the same page (real money for zyte, just courtesy for render, but the same interval works for both).
RENDERED_PAGE_FETCH_INTERVAL_SECONDS = 4 * 60 * 60
# I/O-bound OpenRouter calls (validator or classifier) - a thread pool cuts N sequential calls to N/32; safe to raise since a classifier failure now fails closed (see passes_classifier), not open.
LLM_CALL_CONCURRENCY = 32
# Unlike LLM_CALL_CONCURRENCY, each fetch hits a different company's domain - no shared endpoint to respect, so this can run high (sequential fetching wasted 47s+/run).
FETCH_CONCURRENCY = 25
# ponytail: Zyte is billed per request, unlike every other source kind - gate it
# to a 6h cadence here (at source-selection time, not inside ZyteSource itself)
# rather than giving it its own CloudWatch schedule. This piggybacks on the
# existing source-health table's last_success_at instead of a new field/table;
# that only works because a gated-out ZyteSource is never constructed at all,
# so record_source_success() is never called for it except on a real fetch.


def _string_list(config: dict[str, object], key: str) -> list[str]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def get_target_companies(config: dict[str, object]) -> list[str]:
    return _string_list(config, "companies")


def get_email_recipients(config: dict[str, object]) -> list[str]:
    return _string_list(config, "email_to")


def get_job_types(config: dict[str, object]) -> list[str]:
    return _string_list(config, "job_types") or DEFAULT_JOB_TYPES


def build_company_catalog() -> dict[str, dict[str, object]]:
    return {str(entry["company_name"]).strip().lower(): entry for entry in list_companies()}


FLAT_CATALOG_KINDS = {"apple", "google"}


def resolve_source_specs(companies: list[str], catalog: dict[str, dict[str, object]]) -> list[str]:
    """Auto-adds a source for each selected company the admin catalog maps to
    one - a greenhouse board token, or a dedicated scraper like apple/google -
    so users just pick companies, no hand-typed spec strings. Apple/Google
    aren't parameterized by job_type (their scrapers take no arguments), so
    they're resolved here rather than through build_job_type_sources.

    "community" is always included - it's a free, per-user-filtered shared
    aggregator, not something a user has any real reason to turn off, so
    there's no config knob for it (see resolve_source_specs's old
    base_specs/enabled_sources parameter, removed)."""
    specs = ["community"]
    for company in companies:
        entry = catalog.get(company.strip().lower())
        if not entry:
            continue
        kind = entry.get("source_kind")
        if kind == "greenhouse" and entry.get("board_token"):
            specs.append(f"greenhouse:{entry['company_name']}:{entry['board_token']}")
        elif kind in FLAT_CATALOG_KINDS:
            specs.append(str(kind))
    return specs


def resolve_job_type_pairs(config: dict[str, object]) -> set[tuple[str, str]]:
    """(company, job_type) pairs this config actually wants - not a blind cross
    product of all companies x all job types, so a shared fetch across users
    never scrapes a combination nobody asked for."""
    companies = get_target_companies(config)
    job_types = get_job_types(config)
    return {(company, job_type) for company in companies for job_type in job_types}


def _job_type_url(entry: dict[str, object], job_type: str) -> str | None:
    """URL a "direct"/"zyte" source fetches for this job type - falls back to general_url when there's no distinct page for it."""
    specific_url = entry.get(JOB_TYPE_URL_FIELDS.get(job_type, ""))
    return str(specific_url) if specific_url else (str(entry["general_url"]) if entry.get("general_url") else None)


def _url_job_type_tag(entry: dict[str, object], job_type: str) -> str:
    """Job types sharing the identical resolved URL collapse into one tag, so they merge into a single fetch instead of scraping the same page once per job_type. Shared by zyte and render - both key a Source purely off the resolved URL."""
    target_url = _job_type_url(entry, job_type)
    matching = sorted(jt for jt in JOB_TYPE_URL_FIELDS if _job_type_url(entry, jt) == target_url)
    return "+".join(matching) if matching else job_type


def _ashby_job_type_tag(job_type: str) -> str:
    """Ashby has no distinct "new grad" type - "newgrad" and "fulltime" merge into one tag to avoid double-notifying the same postings."""
    wanted = EMPLOYMENT_TYPE_BY_JOB_TYPE.get(job_type, "FullTime")
    matching = sorted(jt for jt in JOB_TYPE_URL_FIELDS if EMPLOYMENT_TYPE_BY_JOB_TYPE.get(jt, "FullTime") == wanted)
    return "+".join(matching) if matching else job_type


def build_job_type_sources(
    pairs: set[tuple[str, str]], catalog: dict[str, dict[str, object]], *, enforce_fetch_cooldown: bool = True
) -> list[Source]:
    """Sources resolved per (company, job_type) from the catalog, rather than a flat spec string.

    enforce_fetch_cooldown must be False when called just to read back a
    source's .name for filtering (as process_user does) rather than to
    actually fetch() - otherwise the cooldown looks "too recent" right after
    the shared fetch succeeds, and silently drops listings it just paid for.

    Zyte/Ashby job_types resolving to the identical fetch merge into one Source (see _url_job_type_tag/_ashby_job_type_tag).
    """
    sources: list[Source] = []
    seen_names: set[str] = set()
    for company, job_type in pairs:
        entry = catalog.get(company.strip().lower())
        if not entry:
            continue
        kind = entry.get("source_kind")
        if kind == "ashby":
            board_name = entry.get("board_name")
            if not board_name:
                continue
            source = AshbySource(str(entry["company_name"]), str(board_name), job_type)
            source.name = f"ashby:{entry['company_name']}:{_ashby_job_type_tag(job_type)}"
            if source.name in seen_names:
                continue
            seen_names.add(source.name)
            sources.append(source)
        elif kind == "zyte" or kind == "renderer":
            url = _job_type_url(entry, job_type)
            if not url:
                continue
            tag = _url_job_type_tag(entry, job_type)
            if kind == "zyte":
                source: Source = ZyteSource(str(entry["company_name"]), str(url), tag)
            else:
                source = RenderSource(str(entry["company_name"]), str(url), tag)
            if source.name in seen_names:
                continue
            seen_names.add(source.name)
            if not enforce_fetch_cooldown:
                sources.append(source)
            else:
                last_success = get_source_last_success(source.name)
                if last_success is None or time.time() - last_success >= RENDERED_PAGE_FETCH_INTERVAL_SECONDS:
                    sources.append(source)
        elif kind == "workday":
            # board_token is "host:tenant:site" (e.g. "wd5:nvidia:NVIDIAExternalCareerSite").
            board_token = str(entry.get("board_token", ""))
            parts = board_token.split(":")
            if len(parts) == 3:
                host, tenant, site = parts
                sources.append(WorkdaySource(str(entry["company_name"]), host, tenant, site, job_type))
        elif kind == "amazon" and job_type in AMAZON_QUERY_BY_JOB_TYPE:
            sources.append(AmazonJobsSource(str(entry["company_name"]), job_type))
        elif kind == "oracle" and job_type == "intern":
            sources.append(OracleSource(str(entry["company_name"])))
        elif kind == "sitemap" and job_type == "intern":
            url = entry.get("intern_url")
            if url:
                sources.append(SitemapSource(str(entry["company_name"]), str(url)))
    return sources


def classifier_enabled(openrouter_api_key: str | None, fit_prompt: str) -> bool:
    return bool(openrouter_api_key) and bool(fit_prompt) and not fit_prompt.startswith("PLACEHOLDER")


def passes_classifier(
    openrouter_api_key: str | None,
    llm_model: str,
    fit_prompt: str,
    listing: Listing,
    resume_text: str | None = None,
    user_id: str | None = None,
    smtp_user: str = "",
    smtp_pass: str = "",
) -> ClassificationResult | None:
    """fits=True means "notify". Disabled (no key, no prompt, or unedited placeholder
    prompt) fails open, since there's nothing to check against. is_good_fit already
    retries CLASSIFIER_MAX_ATTEMPTS times with backoff internally - an LLMCallError
    here means every one of those attempts failed. Returns None ("couldn't classify
    this run") rather than failing open - failing open used to notify on every
    affected listing regardless of fit, which under a sustained failure (e.g.
    OpenRouter rate-limiting a whole batch under high concurrency) turned into
    notifying on everything, unfiltered. None leaves the listing out of seen_ids, so
    it's just reclassified next run. Persistent failure also pages admins once (not
    every run) via the same alerted-until-recovery pattern as source health."""
    if not classifier_enabled(openrouter_api_key, fit_prompt):
        return ClassificationResult(fits=True, reason="classifier disabled")
    try:
        result = is_good_fit(openrouter_api_key, llm_model, fit_prompt, listing, resume_text, user_id=user_id)
    except LLMCallError as error:
        print(
            f"Classifier failed for {listing.company_name} - {listing.title} after {CLASSIFIER_MAX_ATTEMPTS} attempts, will retry next run: {error}",
            file=sys.stderr,
        )
        consecutive_failures = record_source_failure(CLASSIFIER_HEALTH_KEY)
        if consecutive_failures >= SOURCE_FAILURE_ALERT_THRESHOLD and not is_source_alerted(CLASSIFIER_HEALTH_KEY):
            mark_source_alerted(CLASSIFIER_HEALTH_KEY)
            alert_admins_classifier_failing(str(error), smtp_user, smtp_pass)
        return None
    record_source_success(CLASSIFIER_HEALTH_KEY)
    return result


def _fetch_one_source(source: Source) -> tuple[Source, list[Listing] | Exception, float]:
    started = time.monotonic()
    try:
        return source, source.fetch(), (time.monotonic() - started) * 1000
    except Exception as error:  # a single broken source must not block the rest
        return source, error, (time.monotonic() - started) * 1000


def _source_kind(source: Source) -> str:
    """Every Source's .name is f"{kind}:{company_name}:{job_type}" - reuse that
    instead of adding a separate `kind` attribute to the Source protocol."""
    return source.name.split(":", 1)[0]


def fetch_all_listings(sources: list[Source]) -> tuple[list[Listing], list[str], int]:
    """Returns (listings, source names that just crossed the failure-alert threshold,
    sources_failed count). Fetches run concurrently; side effects happen back on this
    thread as results arrive, not inside worker threads."""
    all_listings: list[Listing] = []
    newly_unhealthy: list[str] = []
    sources_failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=FETCH_CONCURRENCY) as executor:
        for source, result, duration_ms in executor.map(_fetch_one_source, sources):
            if isinstance(result, Exception):
                sources_failed += 1
                print(f"Source '{source.name}' failed: {result}", file=sys.stderr)
                print(json.dumps({
                    "event": "source_fetch", "source": source.name, "kind": _source_kind(source),
                    "success": False, "duration_ms": round(duration_ms), "listing_count": 0,
                }))
                consecutive_failures = record_source_failure(source.name)
                if consecutive_failures >= SOURCE_FAILURE_ALERT_THRESHOLD and not is_source_alerted(source.name):
                    newly_unhealthy.append(source.name)
                    mark_source_alerted(source.name)
                continue
            record_source_success(source.name)
            print(f"Source '{source.name}': {len(result)} matching listing(s)")
            print(json.dumps({
                "event": "source_fetch", "source": source.name, "kind": _source_kind(source),
                "success": True, "duration_ms": round(duration_ms), "listing_count": len(result),
            }))
            all_listings.extend(result)
    return all_listings, newly_unhealthy, sources_failed


def _check_listing_validity(
    listing: Listing, openrouter_api_key: str, llm_model: str
) -> tuple[bool, str]:
    """Prints the validator's rejection here, once per unique listing - not in process_user, which would misattribute a shared verdict once per user who sees it."""
    try:
        is_job_posting, reason = check_is_job_posting(openrouter_api_key, llm_model, listing)
    except LLMCallError as error:
        print(f"Validity check failed for {listing.company_name} - {listing.title}, assuming valid: {error}", file=sys.stderr)
        is_job_posting, reason = True, f"validity check error, assumed valid: {error}"
    if not is_job_posting:
        print(f"validator rejected: {listing.company_name} - {listing.title} ({reason}) [validator: {llm_model}]")
    save_listing_validity(listing.unique_id, is_job_posting=is_job_posting, reason=reason)
    return is_job_posting, reason


def resolve_listing_validity(
    all_listings: list[Listing], openrouter_api_key: str | None, llm_model: str
) -> dict[str, tuple[bool, str]]:
    """Whether each listing is a real job posting vs. scraped page furniture - checked once per listing (shared across users) and cached forever in DynamoDB.

    Cache lookups run sequentially (cheap DynamoDB reads); only listings needing a live OpenRouter call go to a thread pool, since those are I/O-bound.
    """
    validity: dict[str, tuple[bool, str]] = {}
    if not openrouter_api_key:
        return validity

    seen_ids: set[str] = set()
    uncached: list[Listing] = []
    for listing in all_listings:
        if listing.unique_id in seen_ids:
            continue
        seen_ids.add(listing.unique_id)
        cached = get_listing_validity(listing.unique_id)
        if cached is not None:
            validity[listing.unique_id] = (bool(cached["is_job_posting"]), str(cached["reason"]))
        else:
            uncached.append(listing)

    # Structured (not the human-readable prints elsewhere) so the dashboard's metrics
    # page can parse it out of CloudWatch Logs as a per-run backlog data point.
    print(json.dumps({"event": "validator_backlog", "count": len(uncached)}))

    if uncached:
        with concurrent.futures.ThreadPoolExecutor(max_workers=LLM_CALL_CONCURRENCY) as executor:
            futures = {
                executor.submit(_check_listing_validity, listing, openrouter_api_key, llm_model): listing
                for listing in uncached
            }
            for future in concurrent.futures.as_completed(futures):
                listing = futures[future]
                validity[listing.unique_id] = future.result()
    return validity


def _notify_all_admins(subject: str, body: str, smtp_user: str, smtp_pass: str) -> None:
    for admin in list_all_users():
        if not admin.get("is_admin"):
            continue
        admin_id = str(admin["user_id"])
        ntfy_topic = str(admin.get("ntfy_topic", ""))
        if not ntfy_topic:
            continue
        email_recipients = get_email_recipients(load_user_config(admin_id)) or [admin_id]
        try:
            notify_message(ntfy_topic, smtp_user, smtp_pass, email_recipients, subject, body)
        except NotificationError as error:
            print(f"Failed to alert admin {admin_id}: {error}", file=sys.stderr)


def alert_admins(unhealthy_sources: list[str], smtp_user: str, smtp_pass: str) -> None:
    body = (
        f"These sources have failed {SOURCE_FAILURE_ALERT_THRESHOLD}+ runs in a row: "
        f"{', '.join(unhealthy_sources)}"
    )
    _notify_all_admins("job-alerts: source failing", body, smtp_user, smtp_pass)


def alert_admins_classifier_failing(error: str, smtp_user: str, smtp_pass: str) -> None:
    body = (
        f"The classifier has failed {SOURCE_FAILURE_ALERT_THRESHOLD}+ consecutive calls, "
        f"retrying each up to {CLASSIFIER_MAX_ATTEMPTS} times: {error}. Affected listings are "
        "left unseen and retried next run, not notified."
    )
    _notify_all_admins("job-alerts: classifier failing", body, smtp_user, smtp_pass)


def _lambda_recent_errors(function_name: str, window_minutes: int) -> float:
    end_time = time.time()
    start_time = end_time - window_minutes * 60
    response = cloudwatch_client.get_metric_data(
        MetricDataQueries=[{
            "Id": "errors",
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Lambda", "MetricName": "Errors", "Dimensions": [{"Name": "FunctionName", "Value": function_name}]},
                "Period": window_minutes * 60,
                "Stat": "Sum",
            },
        }],
        StartTime=start_time,
        EndTime=end_time,
        ScanBy="TimestampDescending",
    )
    values = response["MetricDataResults"][0]["Values"]
    return values[0] if values else 0.0


def check_lambda_health() -> list[str]:
    """Same source-health/alert-once machinery fetch_all_listings uses for scraper
    sources, applied to dashboard/renderer via their own CloudWatch Errors metric -
    reuses the existing DynamoDB dedup latch and alert_admins path rather than
    standing up CloudWatch Alarms/SNS for two more Lambdas. A CloudWatch hiccup here
    must not fail the scan itself, so failures are swallowed and logged."""
    newly_unhealthy: list[str] = []
    for health_key, function_name in LAMBDA_HEALTH_FUNCTION_NAMES.items():
        try:
            errors = _lambda_recent_errors(function_name, LAMBDA_HEALTH_CHECK_WINDOW_MINUTES)
        except Exception as error:
            print(f"Lambda health check for {function_name} failed: {error}", file=sys.stderr)
            continue
        if errors > 0:
            consecutive_failures = record_source_failure(health_key)
            if consecutive_failures >= SOURCE_FAILURE_ALERT_THRESHOLD and not is_source_alerted(health_key):
                newly_unhealthy.append(health_key)
                mark_source_alerted(health_key)
        else:
            record_source_success(health_key)
    return newly_unhealthy


def alert_admins_lambda_failing(unhealthy_lambdas: list[str], smtp_user: str, smtp_pass: str) -> None:
    body = (
        f"These Lambdas have logged CloudWatch Errors on {SOURCE_FAILURE_ALERT_THRESHOLD}+ consecutive "
        f"checks ({LAMBDA_HEALTH_CHECK_WINDOW_MINUTES}m lookback each): {', '.join(unhealthy_lambdas)}"
    )
    _notify_all_admins("job-alerts: lambda failing", body, smtp_user, smtp_pass)


def _resolve_resume_text(user_id: str) -> str | None:
    """URL mode is fetched live once per user per scan (that's the whole
    point - the user updates the file at that URL directly, no re-sync needed
    here). A dead/unreachable URL shouldn't fail the user's whole scan, just
    means no fit_score this run."""
    profile = load_user_profile(user_id)
    resume_url = str(profile.get("resume_url", ""))
    if resume_url:
        try:
            return fetch_resume_text_from_url(resume_url)
        except ResumeFetchError as error:
            print(f"User {user_id}: could not fetch resume from URL, continuing without fit_score: {error}", file=sys.stderr)
            return None
    return str(profile.get("resume_text", "")) or None


def process_user(
    user: dict[str, object],
    config: dict[str, object],
    all_listings: list[Listing],
    catalog: dict[str, dict[str, object]],
    smtp_user: str,
    smtp_pass: str,
    openrouter_api_key: str | None,
    llm_model: str,
    listing_validity: dict[str, tuple[bool, str]],
) -> tuple[int, int, int, bool]:
    """Returns (new_count, notified_count, dismissed_count, had_notification_failure)."""
    user_id = str(user["user_id"])
    ntfy_topic = str(user.get("ntfy_topic", ""))
    email_recipients = get_email_recipients(config)
    if not ntfy_topic or not email_recipients:
        print(f"User {user_id}: missing ntfy_topic or email_to in config, skipping", file=sys.stderr)
        return 0, 0, 0, False

    user_companies = get_target_companies(config)
    user_companies_lower = {name.lower() for name in user_companies}
    try:
        user_sources: list[Source] = build_sources(resolve_source_specs(user_companies, catalog), user_companies)
    except ValueError as error:
        print(f"User {user_id}: invalid source configuration: {error}", file=sys.stderr)
        return 0, 0, 0, False
    user_sources.extend(build_job_type_sources(resolve_job_type_pairs(config), catalog, enforce_fetch_cooldown=False))
    user_source_names = {source.name for source in user_sources}

    user_listings = [
        listing
        for listing in all_listings
        if listing.source in user_source_names
        and (listing.source != "community" or listing.company_name.strip().lower() in user_companies_lower)
    ]

    seen_ids = load_seen_ids(user_id)
    if not seen_ids:
        print(f"User {user_id}: first run, seeding {len(user_listings)} existing listing(s) without notifying")
        record_listings(user_id, [(listing, "seeded", "", None) for listing in user_listings])
        return 0, 0, 0, False

    fit_prompt = str(config.get("fit_prompt", ""))
    resume_text = _resolve_resume_text(user_id)
    new_listings = [listing for listing in user_listings if listing.unique_id not in seen_ids]
    notified_count = 0
    dismissed_count = 0
    had_notification_failure = False

    # Classify valid listings concurrently, then apply notify/record side effects sequentially below in listing order.
    listings_needing_classification = [
        listing for listing in new_listings if listing_validity.get(listing.unique_id, (True, ""))[0]
    ]
    classifications: dict[str, ClassificationResult | None] = {}
    if listings_needing_classification:
        with concurrent.futures.ThreadPoolExecutor(max_workers=LLM_CALL_CONCURRENCY) as executor:
            futures = {
                executor.submit(
                    passes_classifier,
                    openrouter_api_key,
                    llm_model,
                    fit_prompt,
                    listing,
                    resume_text,
                    user_id,
                    smtp_user,
                    smtp_pass,
                ): listing
                for listing in listings_needing_classification
            }
            for future in concurrent.futures.as_completed(futures):
                listing = futures[future]
                classifications[listing.unique_id] = future.result()

    # Model name goes in the log line only (below), not the stored/displayed reason - the Listings page shows the raw LLM reason text as-is.
    for listing in new_listings:
        is_job_posting, invalid_reason = listing_validity.get(listing.unique_id, (True, ""))
        if not is_job_posting:
            record_listings(user_id, [(listing, "invalid", invalid_reason, None)])
            continue
        classification = classifications[listing.unique_id]
        if classification is None:
            continue  # transient/systemic classifier failure - stays unseen, retried next run

        if not classification.fits:
            record_listings(user_id, [(listing, "dismissed", classification.reason, classification.fit_score)])
            dismissed_count += 1
            print(f"User {user_id}: classifier dismissed: {listing.company_name} - {listing.title} ({classification.reason}) [classifier: {llm_model}]")
            continue
        try:
            notify(ntfy_topic, smtp_user, smtp_pass, email_recipients, listing)
        except NotificationError as error:
            had_notification_failure = True
            print(
                f"User {user_id}: failed to notify for {listing.company_name} - {listing.title}: {error}",
                file=sys.stderr,
            )
            # Not recorded - retried next run, since the notification itself never went out.
            continue
        record_listings(user_id, [(listing, "notified", classification.reason, classification.fit_score)])
        notified_count += 1
        print(f"User {user_id}: notified: {listing.company_name} - {listing.title} [classifier: {llm_model}]")

    return len(new_listings), notified_count, dismissed_count, had_notification_failure


def main() -> int:
    run_started = time.monotonic()
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not smtp_user or not smtp_pass:
        print("Missing required environment variables: SMTP_USER, SMTP_PASS", file=sys.stderr)
        return 1
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    llm_model = get_llm_model()

    active_users = list_active_users()
    if not active_users:
        print("No active users configured", file=sys.stderr)
        return 1

    catalog = build_company_catalog()
    user_configs = {str(user["user_id"]): load_user_config(str(user["user_id"])) for user in active_users}
    all_source_specs: set[str] = set()
    all_companies: set[str] = set()
    all_job_type_pairs: set[tuple[str, str]] = set()
    for config in user_configs.values():
        companies = get_target_companies(config)
        all_companies.update(companies)
        all_source_specs.update(resolve_source_specs(companies, catalog))
        all_job_type_pairs.update(resolve_job_type_pairs(config))

    try:
        shared_sources: list[Source] = build_sources(sorted(all_source_specs), sorted(all_companies))
    except ValueError as error:
        print(f"Invalid source configuration across users: {error}", file=sys.stderr)
        return 1
    shared_sources.extend(build_job_type_sources(all_job_type_pairs, catalog))

    all_listings, newly_unhealthy_sources, sources_failed = fetch_all_listings(shared_sources)
    if newly_unhealthy_sources:
        alert_admins(newly_unhealthy_sources, smtp_user, smtp_pass)

    newly_unhealthy_lambdas = check_lambda_health()
    if newly_unhealthy_lambdas:
        alert_admins_lambda_failing(newly_unhealthy_lambdas, smtp_user, smtp_pass)

    # Checked once here, shared across every user - see resolve_listing_validity's docstring.
    listing_validity = resolve_listing_validity(all_listings, openrouter_api_key, llm_model)

    total_new = total_notified = total_dismissed = 0
    had_notification_failure = False
    for user in active_users:
        user_id = str(user["user_id"])
        new_count, notified_count, dismissed_count, user_had_failure = process_user(
            user, user_configs[user_id], all_listings, catalog, smtp_user, smtp_pass, openrouter_api_key,
            llm_model, listing_validity,
        )
        total_new += new_count
        total_notified += notified_count
        total_dismissed += dismissed_count
        had_notification_failure = had_notification_failure or user_had_failure

    print(
        f"Scan complete: {len(active_users)} user(s), {total_new} new, {total_notified} notified, "
        f"{total_dismissed} dismissed by classifier"
    )
    print(json.dumps({
        "event": "scan_summary",
        "users": len(active_users),
        "new": total_new,
        "notified": total_notified,
        "dismissed": total_dismissed,
        "run_duration_ms": round((time.monotonic() - run_started) * 1000),
        "sources_scanned": len(shared_sources),
        "sources_failed": sources_failed,
    }))
    return 1 if had_notification_failure else 0


def handler(event: dict[str, Any], context: Any) -> None:
    exit_code = main()
    if exit_code != 0:
        raise RuntimeError(f"watch.main() exited with code {exit_code}")


if __name__ == "__main__":
    sys.exit(main())
