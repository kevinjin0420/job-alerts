from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import secrets
import time
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from classifier import (
    CRITERIA_LABEL,
    FIT_SYSTEM_PREAMBLE,
    RESPONSE_INSTRUCTION,
    RESPONSE_INSTRUCTION_WITH_SCORE,
    RESUME_LABEL,
    ClassifierError,
    is_good_fit,
)
from config import SUPPORTED_JOB_TYPES
from notifiers import NotificationError, send_ntfy_message
from resume import ResumeFetchError, extract_resume_text, fetch_resume_text_from_url
from sources.base import Listing
from users import (
    complete_onboarding,
    create_user,
    delete_company,
    delete_user,
    delete_user_resume,
    find_user_by_api_key,
    generate_api_key,
    get_classifier_model,
    get_user,
    list_all_users,
    list_companies,
    list_seen_listings,
    list_source_health,
    load_user_config,
    load_user_profile,
    retry_listing,
    save_classifier_model,
    save_company,
    save_ntfy_topic,
    save_user_config,
    save_user_profile,
    set_user_active,
)

WATCH_LOG_GROUP = "/aws/lambda/job-alerts-watch"
WATCH_FUNCTION_NAME = "job-alerts-watch"
USER_POOL_ID = os.environ["COGNITO_USER_POOL_ID"]
CLIENT_ID = os.environ["COGNITO_CLIENT_ID"]
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

AUTH_ATTEMPTS_TABLE = "job-alerts-auth-attempts"
RATE_LIMIT_WINDOW_SECONDS = 300
RATE_LIMIT_MAX_ATTEMPTS = 10

logs_client = boto3.client("logs")
cloudwatch_client = boto3.client("cloudwatch")
dynamodb_client = boto3.client("dynamodb")
cognito_client = boto3.client("cognito-idp")
lambda_client = boto3.client("lambda")

_SIDEBAR_TEMPLATE = (Path(__file__).parent / "sidebar.html").read_text()
_DEFAULT_NAV_CLASS = "px-3 py-2 rounded-none text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-900"
_ACTIVE_NAV_CLASS = "px-3 py-2 rounded-none font-medium bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"


def _render_sidebar(active_path: str) -> str:
    html = _SIDEBAR_TEMPLATE
    # The admin-only links (Logs/Sources/Admin) also carry a "hidden" prefix -
    # they start hidden regardless of which page is active and are revealed
    # client-side once /api/me confirms admin, so both variants need handling.
    for default_class, active_class in (
        (_DEFAULT_NAV_CLASS, _ACTIVE_NAV_CLASS),
        (f"hidden {_DEFAULT_NAV_CLASS}", f"hidden {_ACTIVE_NAV_CLASS}"),
    ):
        html = html.replace(
            f'data-nav="{active_path}" class="{default_class}"',
            f'data-nav="{active_path}" class="{active_class}"',
        )
    return html


# Each page's __SIDEBAR__ placeholder is substituted once here, at cold start -
# same "compute once, serve free" pattern as the rest of PAGES, so splitting
# the sidebar out doesn't add any per-request cost.
PAGES = {
    path: (Path(__file__).parent / filename).read_text().replace("__SIDEBAR__", _render_sidebar(path))
    for path, filename in {
        "/metrics": "metrics.html",
        "/listings": "listings.html",
        "/config": "config.html",
        "/logs": "logs.html",
        "/admin": "admin.html",
        "/sources": "sources.html",
        "/profile": "profile.html",
        "/onboarding": "onboarding.html",
    }.items()
}
SHARED_JS = (Path(__file__).parent / "shared.js").read_text()

FAILURE_MARKERS = ("fail", "Fail", "FAIL", "Error", "ERROR", "Traceback")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]

    if method == "GET" and path == "/":
        return _redirect("/metrics")
    if method == "GET" and path == "/shared.js":
        return _response(200, "application/javascript", SHARED_JS)
    if method == "GET" and path in PAGES:
        return _response(200, "text/html", PAGES[path])

    source_ip = event["requestContext"]["http"]["sourceIp"]
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}

    if method == "POST" and path == "/api/login":
        if _is_rate_limited(source_ip):
            return _json_response(429, {"error": "too many failed attempts, try again later"})
        return _handle_login(json.loads(event.get("body") or "{}"), source_ip)

    user = _authenticate(headers)
    if user is None:
        return _json_response(401, {"error": "unauthorized"})
    user_id = str(user["user_id"])
    is_admin = bool(user.get("is_admin", False))

    if method == "GET" and path == "/api/me":
        return _json_response(
            200,
            {
                "user_id": user_id,
                "is_admin": is_admin,
                "ntfy_topic": str(user.get("ntfy_topic", "")),
                # Missing on legacy rows created before onboarding existed - treat as already done.
                "onboarding_completed": bool(user.get("onboarding_completed", True)),
                "active": bool(user.get("active", True)),
            },
        )
    if method == "POST" and path == "/api/onboarding/complete":
        complete_onboarding(user_id)
        return _json_response(200, {"status": "completed"})
    if method == "PUT" and path == "/api/me":
        body = json.loads(event.get("body") or "{}")
        ntfy_topic = str(body.get("ntfy_topic", "")).strip()
        if not ntfy_topic:
            return _json_response(400, {"error": "ntfy_topic is required"})
        save_ntfy_topic(user_id, ntfy_topic)
        return _json_response(200, {"status": "saved"})
    if method == "POST" and path == "/api/me/test-notification":
        body = json.loads(event.get("body") or "{}")
        ntfy_topic = str(body.get("ntfy_topic", "")).strip()
        if not ntfy_topic:
            return _json_response(400, {"error": "ntfy_topic is required"})
        try:
            send_ntfy_message(ntfy_topic, "job-alerts test", "If you can see this, your ntfy topic is set up correctly.")
        except NotificationError as error:
            return _json_response(502, {"error": str(error)})
        return _json_response(200, {"status": "sent"})
    if method == "POST" and path == "/api/me/unsubscribe":
        set_user_active(user_id, False)
        return _json_response(200, {"status": "unsubscribed"})
    if method == "POST" and path == "/api/me/resubscribe":
        set_user_active(user_id, True)
        return _json_response(200, {"status": "resubscribed"})
    if method == "DELETE" and path == "/api/me":
        if is_admin:
            return _json_response(400, {"error": "admins can't delete their own account here - ask another admin"})
        try:
            cognito_client.admin_delete_user(UserPoolId=USER_POOL_ID, Username=user_id)
        except ClientError:
            pass  # already gone from Cognito - still clean up our own tables
        delete_user(user_id)
        return _json_response(200, {"status": "deleted"})
    if method == "GET" and path == "/api/options":
        company_names = [str(entry["company_name"]) for entry in list_companies()]
        return _json_response(
            200, {"companies": company_names, "job_types": SUPPORTED_JOB_TYPES}
        )
    if method == "GET" and path == "/api/config":
        config = load_user_config(user_id)
        profile = load_user_profile(user_id)
        has_resume = bool(profile.get("resume_text") or profile.get("resume_url"))
        config["prompt_preview"] = {
            "system_preamble": FIT_SYSTEM_PREAMBLE,
            "criteria_label": CRITERIA_LABEL,
            "resume_label": RESUME_LABEL,
            "has_resume": has_resume,
            "response_instruction": RESPONSE_INSTRUCTION_WITH_SCORE if has_resume else RESPONSE_INSTRUCTION,
        }
        return _json_response(200, config)
    if method == "PUT" and path == "/api/config":
        # Merge onto the current item rather than overwriting it outright -
        # config.html and profile.html (email_to) both PUT here with only the
        # fields they own; a blind overwrite from either would wipe the other's.
        current_config = load_user_config(user_id)
        current_config.update(json.loads(event.get("body") or "{}"))
        save_user_config(user_id, current_config)
        return _json_response(200, {"status": "saved"})
    if method == "GET" and path == "/api/logs":
        if not is_admin:
            return _json_response(403, {"error": "admin only"})
        return _json_response(200, {"events": _recent_log_events()})
    if method == "GET" and path == "/api/metrics":
        return _json_response(200, _recent_metrics())
    if method == "POST" and path == "/api/apikey":
        return _json_response(200, {"api_key": generate_api_key(user_id)})
    if method == "GET" and path == "/api/listings":
        listings = [item for item in list_seen_listings(user_id) if item.get("status") != "invalid"]
        return _json_response(200, {"listings": listings})
    if method == "DELETE" and path.startswith("/api/listings/"):
        retry_listing(user_id, path[len("/api/listings/") :])
        return _json_response(200, {"status": "removed"})
    if method == "POST" and path == "/api/test-classifier":
        return _handle_test_classifier(user_id, json.loads(event.get("body") or "{}"))
    if method == "GET" and path == "/api/profile":
        return _json_response(200, _profile_with_live_preview(user_id))
    if method == "POST" and path == "/api/profile/resume":
        return _handle_resume_upload(user_id, json.loads(event.get("body") or "{}"))
    if method == "POST" and path == "/api/profile/resume-url":
        return _handle_resume_url_fetch(user_id, json.loads(event.get("body") or "{}"))
    if method == "DELETE" and path == "/api/profile/resume":
        delete_user_resume(user_id)
        return _json_response(200, {"status": "deleted"})

    if path.startswith("/api/admin/"):
        if not is_admin:
            return _json_response(403, {"error": "admin only"})
        return _handle_admin(method, path, event, user_id)

    return _json_response(404, {"error": "not found"})


def _handle_test_classifier(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    if not OPENROUTER_API_KEY:
        return _json_response(400, {"error": "classifier not configured (no OPENROUTER_API_KEY)"})
    fit_prompt = str(body.get("fit_prompt", ""))
    if not fit_prompt:
        return _json_response(400, {"error": "fit_prompt is required"})
    classifier_model = get_classifier_model()
    sample = Listing(
        source="test",
        id="test",
        company_name=str(body.get("company_name", "")),
        title=str(body.get("title", "")),
        locations=[loc.strip() for loc in str(body.get("locations", "")).split(",") if loc.strip()],
        url="",
        description=str(body.get("description", "")) or None,
    )
    resume_text = _resolve_resume_text(load_user_profile(user_id))
    try:
        # Single attempt, 20s cap - stays under API Gateway's hard 30s integration timeout.
        result = is_good_fit(
            OPENROUTER_API_KEY, classifier_model, fit_prompt, sample, resume_text, max_attempts=1, request_timeout_seconds=20
        )
    except ClassifierError as error:
        return _json_response(502, {"error": str(error)})
    return _json_response(200, {"fits": result.fits, "reason": result.reason, "fit_score": result.fit_score})


def _resolve_resume_text(profile: dict[str, Any]) -> str | None:
    """URL mode is fetched live every time (that's the point - no re-syncing
    the app when the file at that URL changes); upload mode uses the cached
    text from upload time, since there's no live source to refetch from."""
    resume_url = str(profile.get("resume_url", ""))
    if resume_url:
        try:
            return fetch_resume_text_from_url(resume_url)
        except ResumeFetchError:
            return None
    return str(profile.get("resume_text", "")) or None


def _profile_with_live_preview(user_id: str) -> dict[str, Any]:
    profile = load_user_profile(user_id)
    resume_url = str(profile.get("resume_url", ""))
    if resume_url:
        try:
            profile["resume_text"] = fetch_resume_text_from_url(resume_url)
        except ResumeFetchError as error:
            profile["resume_fetch_error"] = str(error)
    return profile


def _handle_resume_upload(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    filename = str(body.get("filename", "resume.pdf")).strip() or "resume.pdf"
    content_base64 = str(body.get("content_base64", ""))
    if not content_base64:
        return _json_response(400, {"error": "content_base64 required"})
    try:
        pdf_bytes = base64.b64decode(content_base64, validate=True)
    except (ValueError, TypeError):
        return _json_response(400, {"error": "content_base64 is not valid base64"})

    try:
        resume_text = extract_resume_text(pdf_bytes)
    except ResumeFetchError as error:
        return _json_response(400, {"error": str(error)})

    save_user_profile(user_id, resume_text=resume_text, resume_filename=filename)
    return _json_response(200, load_user_profile(user_id))


def _handle_resume_url_fetch(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    url = str(body.get("url", "")).strip()
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return _json_response(400, {"error": "a valid http(s) url is required"})

    # Fetched here only to validate the URL actually works and to return an
    # immediate preview - the result is never persisted, since the whole
    # point of URL mode is fetching fresh every time it's actually needed.
    try:
        resume_text = fetch_resume_text_from_url(url)
    except ResumeFetchError as error:
        return _json_response(400, {"error": str(error)})

    filename = parsed_url.path.rsplit("/", 1)[-1] or "resume.pdf"
    save_user_profile(user_id, resume_filename=filename, resume_url=url)
    profile = load_user_profile(user_id)
    profile["resume_text"] = resume_text
    return _json_response(200, profile)


def _authenticate(headers: dict[str, str]) -> dict[str, Any] | None:
    api_key = headers.get("x-api-key")
    if api_key:
        return find_user_by_api_key(api_key)

    auth_header = headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    access_token = auth_header[len("Bearer ") :]
    try:
        response = cognito_client.get_user(AccessToken=access_token)
    except ClientError:
        return None
    email = next((attr["Value"] for attr in response["UserAttributes"] if attr["Name"] == "email"), None)
    return get_user(email) if email else None


def _handle_login(body: dict[str, Any], source_ip: str) -> dict[str, Any]:
    email = str(body.get("email", "")).strip()

    if body.get("new_password"):
        try:
            response = cognito_client.respond_to_auth_challenge(
                ClientId=CLIENT_ID,
                ChallengeName="NEW_PASSWORD_REQUIRED",
                Session=str(body.get("session", "")),
                ChallengeResponses={"USERNAME": email, "NEW_PASSWORD": str(body["new_password"])},
            )
        except ClientError as error:
            _record_failed_auth(source_ip)
            return _json_response(401, {"error": str(error)})
        _clear_failed_auth(source_ip)
        return _json_response(200, _tokens_from_auth_result(response["AuthenticationResult"]))

    try:
        response = cognito_client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": email, "PASSWORD": str(body.get("password", ""))},
        )
    except ClientError:
        _record_failed_auth(source_ip)
        return _json_response(401, {"error": "invalid email or password"})

    if response.get("ChallengeName") == "NEW_PASSWORD_REQUIRED":
        return _json_response(200, {"challenge": "NEW_PASSWORD_REQUIRED", "session": response["Session"]})

    _clear_failed_auth(source_ip)
    return _json_response(200, _tokens_from_auth_result(response["AuthenticationResult"]))


def _tokens_from_auth_result(auth_result: dict[str, Any]) -> dict[str, Any]:
    return {"access_token": auth_result["AccessToken"], "expires_in": auth_result["ExpiresIn"]}


def _handle_admin(method: str, path: str, event: dict[str, Any], admin_user_id: str) -> dict[str, Any]:
    if method == "GET" and path == "/api/admin/users":
        users = list_all_users()
        for user in users:
            user.pop("api_key_hash", None)
        return _json_response(200, {"users": users})

    if method == "POST" and path == "/api/admin/users":
        body = json.loads(event.get("body") or "{}")
        email = str(body.get("email", "")).strip()
        if not email:
            return _json_response(400, {"error": "email required"})
        ntfy_topic = f"job-alerts-{secrets.token_hex(6)}"
        cognito_client.admin_create_user(
            UserPoolId=USER_POOL_ID,
            Username=email,
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
            DesiredDeliveryMediums=["EMAIL"],
        )
        create_user(email, is_admin=False, ntfy_topic=ntfy_topic)
        return _json_response(200, {"status": "invited", "ntfy_topic": ntfy_topic})

    if method == "DELETE" and path.startswith("/api/admin/users/"):
        target_user_id = path[len("/api/admin/users/") :]
        try:
            cognito_client.admin_delete_user(UserPoolId=USER_POOL_ID, Username=target_user_id)
        except ClientError:
            pass  # already gone from Cognito - still clean up our own tables
        delete_user(target_user_id)
        return _json_response(200, {"status": "deleted"})

    if method == "GET" and path == "/api/admin/companies":
        return _json_response(200, {"companies": list_companies()})

    if method == "POST" and path == "/api/admin/companies":
        body = json.loads(event.get("body") or "{}")
        name = str(body.get("company_name", "")).strip()
        if not name:
            return _json_response(400, {"error": "company_name required"})
        source_kind = str(body.get("source_kind", "community"))
        save_company(
            name,
            source_kind,
            admin_user_id,
            board_token=str(body.get("board_token", "")).strip() or None,
            board_name=str(body.get("board_name", "")).strip() or None,
            intern_url=str(body.get("intern_url", "")).strip() or None,
            newgrad_url=str(body.get("newgrad_url", "")).strip() or None,
            fulltime_url=str(body.get("fulltime_url", "")).strip() or None,
        )
        return _json_response(200, {"status": "saved"})

    if method == "DELETE" and path.startswith("/api/admin/companies/"):
        delete_company(path[len("/api/admin/companies/") :])
        return _json_response(200, {"status": "deleted"})

    if method == "GET" and path == "/api/admin/source-health":
        return _json_response(200, {"sources": list_source_health()})

    if method == "GET" and path == "/api/admin/settings":
        return _json_response(200, {"classifier_model": get_classifier_model()})

    if method == "PUT" and path == "/api/admin/settings":
        body = json.loads(event.get("body") or "{}")
        classifier_model = str(body.get("classifier_model", "")).strip()
        if not classifier_model:
            return _json_response(400, {"error": "classifier_model is required"})
        save_classifier_model(classifier_model)
        return _json_response(200, {"status": "saved"})

    if method == "POST" and path == "/api/admin/trigger-scan":
        lambda_client.invoke(FunctionName=WATCH_FUNCTION_NAME, InvocationType="Event")
        return _json_response(200, {"status": "triggered"})

    return _json_response(404, {"error": "not found"})


def _is_rate_limited(source_ip: str) -> bool:
    response = dynamodb_client.get_item(TableName=AUTH_ATTEMPTS_TABLE, Key={"source_ip": {"S": source_ip}})
    item = response.get("Item")
    if not item:
        return False
    if time.time() - int(item["window_start"]["N"]) > RATE_LIMIT_WINDOW_SECONDS:
        return False
    return int(item["failed_count"]["N"]) >= RATE_LIMIT_MAX_ATTEMPTS


def _record_failed_auth(source_ip: str) -> None:
    now = int(time.time())
    response = dynamodb_client.get_item(TableName=AUTH_ATTEMPTS_TABLE, Key={"source_ip": {"S": source_ip}})
    item = response.get("Item")
    if item and now - int(item["window_start"]["N"]) <= RATE_LIMIT_WINDOW_SECONDS:
        dynamodb_client.update_item(
            TableName=AUTH_ATTEMPTS_TABLE,
            Key={"source_ip": {"S": source_ip}},
            UpdateExpression="SET failed_count = failed_count + :one",
            ExpressionAttributeValues={":one": {"N": "1"}},
        )
        return
    dynamodb_client.put_item(
        TableName=AUTH_ATTEMPTS_TABLE,
        Item={
            "source_ip": {"S": source_ip},
            "window_start": {"N": str(now)},
            "failed_count": {"N": "1"},
        },
    )


def _clear_failed_auth(source_ip: str) -> None:
    dynamodb_client.delete_item(TableName=AUTH_ATTEMPTS_TABLE, Key={"source_ip": {"S": source_ip}})


def _recent_log_events(hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    start_time_ms = int((time.time() - hours * 3600) * 1000)
    response = logs_client.filter_log_events(
        logGroupName=WATCH_LOG_GROUP,
        startTime=start_time_ms,
        limit=limit,
        interleaved=True,
    )
    events = [
        {
            "timestamp": event["timestamp"],
            "message": event["message"].rstrip("\n"),
            "is_failure": any(marker in event["message"] for marker in FAILURE_MARKERS),
        }
        for event in response.get("events", [])
    ]
    events.sort(key=lambda event: event["timestamp"], reverse=True)
    return events


def _metric_query(
    query_id: str, period: int, namespace: str, metric_name: str, stat: str, function_name: str | None
) -> dict[str, Any]:
    dimensions = [{"Name": "FunctionName", "Value": function_name}] if function_name else []
    return {
        "Id": query_id,
        "MetricStat": {
            "Metric": {"Namespace": namespace, "MetricName": metric_name, "Dimensions": dimensions},
            "Period": period,
            "Stat": stat,
        },
    }


def _last_invocation_time(hours: int = 1) -> str | None:
    """Exact last-invocation timestamp from logs, not a CloudWatch metric bucket
    start (which can be up to one period-width earlier than the real event)."""
    start_time_ms = int((time.time() - hours * 3600) * 1000)
    response = logs_client.filter_log_events(
        logGroupName=WATCH_LOG_GROUP,
        startTime=start_time_ms,
        filterPattern="REPORT RequestId",
        interleaved=True,
    )
    events = response.get("events", [])
    if not events:
        return None
    latest_ms = max(event["timestamp"] for event in events)
    return datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).isoformat()


def _duration_series(hours: int) -> list[dict[str, Any]]:
    """Per-invocation Duration, not the single 24h average - period=300 lines up
    with SCHEDULE_RATE so each real run gets its own point on the chart."""
    end_time = time.time()
    start_time = end_time - hours * 3600
    response = cloudwatch_client.get_metric_data(
        MetricDataQueries=[_metric_query("duration_series", 300, "AWS/Lambda", "Duration", "Average", WATCH_FUNCTION_NAME)],
        StartTime=start_time,
        EndTime=end_time,
        ScanBy="TimestampAscending",
    )
    result = response["MetricDataResults"][0]
    return [
        {"timestamp": timestamp.isoformat(), "value": round(value, 2)}
        for timestamp, value in zip(result["Timestamps"], result["Values"])
    ]


MAX_LOG_SCAN_PAGES = 10


def _structured_log_series(event_name: str, hours: int) -> list[dict[str, Any]]:
    """Parses watch.py's `print(json.dumps({"event": event_name, ...}))` lines
    into per-run data points, keyed by the log event's own timestamp.

    filter_log_events can return an empty page with nextToken still set - a
    single call finishing with zero events does NOT mean there are no matches,
    only that it gave up scanning before finding one (this log group is noisy
    enough that a bare unpaginated call was silently returning nothing despite
    real matches existing). FilterLogEvents always scans forward from startTime
    with no way to reverse that order, so this pages until it either finds
    matches or exhausts MAX_LOG_SCAN_PAGES.
    """
    start_time_ms = int((time.time() - hours * 3600) * 1000)
    parsed: list[dict[str, Any]] = []
    next_token: str | None = None
    for _ in range(MAX_LOG_SCAN_PAGES):
        kwargs: dict[str, Any] = {
            "logGroupName": WATCH_LOG_GROUP,
            "startTime": start_time_ms,
            "filterPattern": event_name,
            "interleaved": True,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        response = logs_client.filter_log_events(**kwargs)
        for event in response.get("events", []):
            try:
                payload = json.loads(event["message"])
            except json.JSONDecodeError:
                continue
            if payload.get("event") != event_name:
                continue
            payload["timestamp"] = datetime.fromtimestamp(event["timestamp"] / 1000, tz=timezone.utc).isoformat()
            parsed.append(payload)
        next_token = response.get("nextToken")
        if not next_token:
            break
    parsed.sort(key=lambda item: item["timestamp"])
    return parsed


def _invocation_metrics(start_time: float, end_time: float) -> dict[str, Any]:
    queries = [
        _metric_query("invocations", 300, "AWS/Lambda", "Invocations", "Sum", WATCH_FUNCTION_NAME),
        _metric_query("errors", 86400, "AWS/Lambda", "Errors", "Sum", WATCH_FUNCTION_NAME),
        _metric_query("avg_duration_ms", 86400, "AWS/Lambda", "Duration", "Average", WATCH_FUNCTION_NAME),
    ]
    response = cloudwatch_client.get_metric_data(
        MetricDataQueries=queries,
        StartTime=start_time,
        EndTime=end_time,
        ScanBy="TimestampDescending",
    )
    by_id = {result["Id"]: result for result in response["MetricDataResults"]}

    def latest(query_id: str) -> float | None:
        values = by_id[query_id]["Values"]
        return round(values[0], 2) if values else None

    invocation_values = by_id["invocations"]["Values"]
    return {
        "invocations_24h": round(sum(invocation_values), 2),
        "errors_24h": latest("errors"),
        "avg_duration_ms": latest("avg_duration_ms"),
    }


def _recent_metrics(hours: int = 24) -> dict[str, Any]:
    end_time = time.time()
    start_time = end_time - hours * 3600

    # Independent CloudWatch/Logs round-trips, dispatched concurrently rather than
    # one after another - filter_log_events scanning a noisy 24h log group for a
    # term with no matches can alone take several seconds, and serializing five of
    # these back to back is what was making the metrics page painfully slow to load.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        invocation_metrics_future = executor.submit(_invocation_metrics, start_time, end_time)
        last_ran_future = executor.submit(_last_invocation_time)
        duration_series_future = executor.submit(_duration_series, hours)
        throughput_future = executor.submit(_structured_log_series, "scan_summary", hours)
        backlog_future = executor.submit(_structured_log_series, "classifier_backlog", hours)

        invocation_metrics = invocation_metrics_future.result()
        last_ran = last_ran_future.result()
        duration_series = duration_series_future.result()
        throughput_series = throughput_future.result()
        backlog_series = backlog_future.result()

    return {
        **invocation_metrics,
        "last_ran": last_ran,
        "duration_series": duration_series,
        "throughput_series": throughput_series,
        "backlog_series": backlog_series,
    }


def _redirect(location: str) -> dict[str, Any]:
    return {"statusCode": 302, "headers": {"location": location}, "body": ""}


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return _response(status_code, "application/json", json.dumps(body, default=_json_default))


def _response(status_code: int, content_type: str, body: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": content_type},
        "body": body,
    }
