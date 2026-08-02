from __future__ import annotations

import base64
import concurrent.futures
import json
import mimetypes
import os
import re
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
    is_good_fit,
)
from config import SUPPORTED_JOB_TYPES
from llm import LLMCallError
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
    get_llm_model,
    get_user,
    list_all_users,
    list_companies,
    list_llm_calls,
    list_seen_listings,
    list_source_health,
    load_user_config,
    load_user_profile,
    retry_listing,
    save_company,
    save_llm_model,
    save_ntfy_topic,
    save_user_config,
    save_user_profile,
    set_user_active,
)

# Inlined instead of importing watch.py, which would drag in every scraper module.
DEFAULT_JOB_TYPES = ["intern"]
SOURCE_FAILURE_ALERT_THRESHOLD = 3


def _config_string_list(config: dict[str, Any], key: str) -> list[str]:
    raw = config.get(key, [])
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


WATCH_LOG_GROUP = "/aws/lambda/job-alerts-watch"
WATCH_FUNCTION_NAME = "job-alerts-watch"
DASHBOARD_LOG_GROUP = "/aws/lambda/job-alerts-dashboard"
DASHBOARD_FUNCTION_NAME = "job-alerts-dashboard"
RENDERER_LOG_GROUP = "/aws/lambda/job-alerts-renderer"
RENDERER_FUNCTION_NAME = "job-alerts-renderer"
LOG_GROUPS_BY_LAMBDA = {"watch": WATCH_LOG_GROUP, "dashboard": DASHBOARD_LOG_GROUP, "renderer": RENDERER_LOG_GROUP}
LAMBDA_FUNCTION_NAMES = {"watch": WATCH_FUNCTION_NAME, "dashboard": DASHBOARD_FUNCTION_NAME, "renderer": RENDERER_FUNCTION_NAME}
DEFAULT_LAMBDA_KEY = "watch"
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

# Read once at cold start. Second path is the local checkout layout, so tests can import this.
_DIST_DIR = next(
    (
        candidate
        for candidate in (Path(__file__).parent / "dist", Path(__file__).parent.parent / "frontend" / "dist")
        if candidate.is_dir()
    ),
    None,
)
SPA_INDEX_HTML: bytes | None = (
    (_DIST_DIR / "index.html").read_bytes() if _DIST_DIR and (_DIST_DIR / "index.html").is_file() else None
)
SPA_ASSETS: dict[str, bytes] = (
    {f"/assets/{asset.name}": asset.read_bytes() for asset in (_DIST_DIR / "assets").iterdir() if asset.is_file()}
    if _DIST_DIR and (_DIST_DIR / "assets").is_dir()
    else {}
)
# Vite copies public/* here unhashed, unlike /assets/*, so these can't be cached immutably.
SPA_ROOT_FILES: dict[str, bytes] = (
    {f"/{f.name}": f.read_bytes() for f in _DIST_DIR.iterdir() if f.is_file() and f.name != "index.html"}
    if _DIST_DIR
    else {}
)

FAILURE_MARKERS = ("fail", "Fail", "FAIL", "Error", "ERROR", "Traceback")
# These lines embed the classifier's free-text reasoning, which often contains "fail"/"Error" as ordinary words (e.g. "Fails multiple criteria") - not an actual failure.
NON_FAILURE_LINE_MARKERS = ("classifier dismissed:", "validator rejected:")
# Structured {"event": ...} lines (scan_summary, source_fetch, etc.) carry their own explicit
# failure signal - checked by field below instead of substring, so a JSON key name like
# scan_summary's "sources_failed" can't trip FAILURE_MARKERS' "fail" match at count 0.
STRUCTURED_FAILURE_EVENTS = ("render_failure",)


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]

    if method == "GET" and path in SPA_ASSETS:
        # Vite content-hashes every asset filename, so a given URL is immutable.
        return _asset_response(SPA_ASSETS[path], path, "public, max-age=31536000, immutable")
    if method == "GET" and path in SPA_ROOT_FILES:
        return _asset_response(SPA_ROOT_FILES[path], path, "public, max-age=3600")
    if method == "GET" and not path.startswith("/api/"):
        # SPA fallback - the client-side router owns every non-API path. index.html
        # must not be cached or a deploy's new asset hashes are never picked up.
        if SPA_INDEX_HTML is None:
            return _json_response(500, {"error": "frontend bundle missing - run npm run build in frontend/"})
        return _asset_response(SPA_INDEX_HTML, "index.html", "no-cache")

    source_ip = event["requestContext"]["http"]["sourceIp"]
    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}

    if method == "POST" and path == "/api/login":
        if _is_rate_limited(source_ip):
            print(json.dumps({"event": "auth_rejected", "reason": "rate_limited", "path": "/api/login"}))
            return _json_response(429, {"error": "too many failed attempts, try again later"})
        return _handle_login(json.loads(event.get("body") or "{}"), source_ip)

    # Authenticated by the refresh token in the body, not a bearer header, so it sits above _authenticate.
    if method == "POST" and path == "/api/refresh":
        if _is_rate_limited(source_ip):
            print(json.dumps({"event": "auth_rejected", "reason": "rate_limited", "path": "/api/refresh"}))
            return _json_response(429, {"error": "too many failed attempts, try again later"})
        return _handle_refresh(json.loads(event.get("body") or "{}"), source_ip)

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
        # The Config and Profile (email_to) pages both PUT here with only the
        # fields they own; a blind overwrite from either would wipe the other's.
        current_config = load_user_config(user_id)
        current_config.update(json.loads(event.get("body") or "{}"))
        save_user_config(user_id, current_config)
        return _json_response(200, {"status": "saved"})
    if method == "GET" and path == "/api/logs":
        if not is_admin:
            return _json_response(403, {"error": "admin only"})
        params = event.get("queryStringParameters") or {}
        log_group = LOG_GROUPS_BY_LAMBDA.get(params.get("lambda", ""), LOG_GROUPS_BY_LAMBDA[DEFAULT_LAMBDA_KEY])
        query = params.get("q", "").strip()
        before = float(params["before"]) if params.get("before") else None
        if query:
            return _json_response(200, _search_log_lines(log_group, query, before, SEARCH_PAGE_LIMIT))
        if params.get("mode") == "runs":
            count = int(params.get("count", DEFAULT_RUNS_PAGE_SIZE))
            return _json_response(200, _fetch_runs_page(log_group, before, count))
        return _json_response(200, {"events": _recent_log_events(log_group)})
    if method == "GET" and path == "/api/llm-logs":
        if not is_admin:
            return _json_response(403, {"error": "admin only"})
        params = event.get("queryStringParameters") or {}
        before = params.get("before") or None
        events, next_cursor = list_llm_calls(before, LLM_LOG_PAGE_LIMIT)
        return _json_response(200, {"events": events, "next_cursor": next_cursor})
    if method == "GET" and path == "/api/metrics":
        params = event.get("queryStringParameters") or {}
        range_key = params.get("range", DEFAULT_METRICS_RANGE)
        minutes = METRICS_RANGE_PRESETS_MINUTES.get(range_key, METRICS_RANGE_PRESETS_MINUTES[DEFAULT_METRICS_RANGE])
        lambda_key = params.get("lambda", DEFAULT_LAMBDA_KEY)
        if lambda_key not in LAMBDA_FUNCTION_NAMES:
            lambda_key = DEFAULT_LAMBDA_KEY
        return _json_response(200, _recent_metrics(minutes, lambda_key))
    if method == "POST" and path == "/api/apikey":
        return _json_response(200, {"api_key": generate_api_key(user_id)})
    if method == "GET" and path == "/api/listings":
        range_key = (event.get("queryStringParameters") or {}).get("range")
        since = time.time() - METRICS_RANGE_PRESETS_MINUTES[range_key] * 60 if range_key in METRICS_RANGE_PRESETS_MINUTES else None
        listings = [item for item in list_seen_listings(user_id, since=since) if item.get("status") != "invalid"]
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
    llm_model = get_llm_model()
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
            OPENROUTER_API_KEY, llm_model, fit_prompt, sample, resume_text, max_attempts=1, request_timeout_seconds=20
        )
    except LLMCallError as error:
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
    tokens: dict[str, Any] = {"access_token": auth_result["AccessToken"], "expires_in": auth_result["ExpiresIn"]}
    # Absent on a REFRESH_TOKEN_AUTH result - Cognito does not reissue one, the caller keeps what it has.
    refresh_token = auth_result.get("RefreshToken")
    if refresh_token:
        tokens["refresh_token"] = refresh_token
    return tokens


def _handle_refresh(body: dict[str, Any], source_ip: str) -> dict[str, Any]:
    """Failures count against the per-IP budget, or this is an unmetered oracle for guessing tokens."""
    refresh_token = str(body.get("refresh_token", "")).strip()
    if not refresh_token:
        return _json_response(400, {"error": "refresh_token is required"})
    try:
        response = cognito_client.initiate_auth(
            ClientId=CLIENT_ID,
            AuthFlow="REFRESH_TOKEN_AUTH",
            AuthParameters={"REFRESH_TOKEN": refresh_token},
        )
    except ClientError:
        _record_failed_auth(source_ip)
        return _json_response(401, {"error": "invalid or expired refresh token"})
    _clear_failed_auth(source_ip)
    return _json_response(200, _tokens_from_auth_result(response["AuthenticationResult"]))


def _handle_admin(method: str, path: str, event: dict[str, Any], admin_user_id: str) -> dict[str, Any]:
    if method == "GET" and path == "/api/admin/users":
        users = list_all_users()
        for user in users:
            user.pop("api_key_hash", None)
            config = load_user_config(str(user["user_id"]))
            job_types = _config_string_list(config, "job_types") or DEFAULT_JOB_TYPES
            user["query_count"] = len(_config_string_list(config, "companies")) * len(job_types)
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
        return _json_response(200, {"llm_model": get_llm_model()})

    if method == "PUT" and path == "/api/admin/settings":
        body = json.loads(event.get("body") or "{}")
        llm_model = str(body.get("llm_model", "")).strip()
        if not llm_model:
            return _json_response(400, {"error": "llm_model is required"})
        save_llm_model(llm_model)
        return _json_response(200, {"status": "saved"})

    if method == "POST" and path == "/api/admin/trigger-scan":
        lambda_client.invoke(FunctionName=WATCH_FUNCTION_NAME, InvocationType="Event")
        return _json_response(200, {"status": "triggered"})

    if method == "GET" and path == "/api/admin/activity":
        range_key = (event.get("queryStringParameters") or {}).get("range", DEFAULT_METRICS_RANGE)
        minutes = METRICS_RANGE_PRESETS_MINUTES.get(range_key, METRICS_RANGE_PRESETS_MINUTES[DEFAULT_METRICS_RANGE])
        return _json_response(200, _admin_activity(minutes))

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


def _is_structured_failure_event(event: dict[str, Any]) -> bool:
    name = event.get("event")
    if name in STRUCTURED_FAILURE_EVENTS:
        return True
    if name == "scan_summary":
        return bool(event.get("sources_failed"))
    if name == "source_fetch":
        return event.get("success") is False
    return False


def _is_failure_line(message: str) -> bool:
    try:
        event = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        event = None
    if isinstance(event, dict) and "event" in event:
        return _is_structured_failure_event(event)
    return not any(marker in message for marker in NON_FAILURE_LINE_MARKERS) and any(
        marker in message for marker in FAILURE_MARKERS
    )


_NODE_RUNTIME_LOG_PREFIX = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z\s+[0-9a-f-]{36}\s+(?:INFO|WARN|ERROR|DEBUG|TRACE)\s+"
)


def _strip_runtime_log_prefix(message: str) -> str:
    """Node.js Lambda's console.log auto-prepends its own timestamp/requestId/level -
    redundant with the CloudWatch event timestamp we already display, so drop it."""
    return _NODE_RUNTIME_LOG_PREFIX.sub("", message, count=1)


def _parse_log_event_row(row: list[dict[str, str]]) -> dict[str, Any] | None:
    fields = {field["field"]: field["value"] for field in row}
    timestamp = _parse_insights_timestamp(fields.get("@timestamp", ""))
    if timestamp is None:
        return None
    message = _strip_runtime_log_prefix(fields.get("@message", "").rstrip("\n"))
    return {"timestamp": timestamp, "message": message, "is_failure": _is_failure_line(message)}


def _recent_log_events(log_group: str, hours: int = 24, limit: int = 500) -> list[dict[str, Any]]:
    """Via Logs Insights, not FilterLogEvents - FilterLogEvents scans forward
    from startTime with no pagination here, so its `limit` filled up with the
    OLDEST events in the window (a single watch invocation alone can log
    hundreds to thousands of lines) and the genuinely newest logs were simply
    never fetched at all, no matter how the returned subset was then sorted.
    `sort @timestamp desc | limit N` asks Insights for the newest N directly."""
    query_string = f"fields @timestamp, @message | sort @timestamp desc | limit {limit}"
    end_time = time.time()
    start_time = end_time - hours * 3600
    events = [_parse_log_event_row(row) for row in _run_insights_query(query_string, start_time, end_time, log_group)]
    return [event for event in events if event is not None]


_START_REQUEST_ID_PATTERN = re.compile(r"^START RequestId: (\S+)")
_END_REQUEST_ID_PATTERN = re.compile(r"^END RequestId: (\S+)")
_REPORT_REQUEST_ID_PATTERN = re.compile(r"^REPORT RequestId: (\S+)\s+Duration: ([\d.]+) ms")

def _group_log_runs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Python port of frontend/src/lib/groupLogRuns.ts - events must already be sorted
    ascending by timestamp. CloudWatch's @requestId field only auto-populates on the
    platform's own START/END/REPORT lines, not on print() output, so an ordinary line
    is attributed to whichever run is currently open on a stack rather than by a direct
    field match. Returns runs newest-first, matching every other list in this app."""
    runs: list[dict[str, Any]] = []
    runs_by_id: dict[str, dict[str, Any]] = {}
    open_stack: list[dict[str, Any]] = []
    unknown_run: dict[str, Any] | None = None

    def current_run() -> dict[str, Any]:
        nonlocal unknown_run
        if open_stack:
            return open_stack[-1]
        if unknown_run is None:
            unknown_run = {"id": None, "startTime": None, "endTime": None, "durationMs": None, "lines": [], "failureCount": 0}
            runs.append(unknown_run)
        return unknown_run

    for event in events:
        message = event["message"]
        start_match = _START_REQUEST_ID_PATTERN.match(message)
        start_id = start_match.group(1) if start_match else None
        if start_id is not None:
            run: dict[str, Any] = {
                "id": start_id,
                "startTime": event["timestamp"],
                "endTime": None,
                "durationMs": None,
                "lines": [],
                "failureCount": 0,
            }
            runs.append(run)
            runs_by_id[start_id] = run
            open_stack.append(run)

        end_match = _END_REQUEST_ID_PATTERN.match(message)
        end_id = end_match.group(1) if end_match else None
        report_match = _REPORT_REQUEST_ID_PATTERN.match(message)
        tagged_id = start_id or end_id or (report_match.group(1) if report_match else None)
        run = runs_by_id.get(tagged_id) if tagged_id else None
        if run is None:
            run = current_run()

        run["lines"].append(event)
        if event.get("is_failure"):
            run["failureCount"] += 1
        if report_match is not None:
            run["durationMs"] = float(report_match.group(2))
        if end_id is not None:
            run["endTime"] = event["timestamp"]
            for i in range(len(open_stack) - 1, -1, -1):
                if open_stack[i] is run:
                    del open_stack[i]
                    break

    return list(reversed(runs))


def _run_boundaries(log_group: str, before: float, count: int, lookback_minutes: int) -> list[tuple[str, float]]:
    """Up to `count` (request_id, start_epoch) pairs for the most recent START
    RequestId lines strictly before `before` - cheap and precise, since START lines
    are short and their timestamp *is* the run's start, so a page of N runs never
    has to guess how many raw lines it'll contain."""
    query_string = f"fields @timestamp, @message | filter @message like /^START RequestId/ | sort @timestamp desc | limit {count}"
    start_time = before - lookback_minutes * 60
    boundaries: list[tuple[str, float]] = []
    for row in _run_insights_query(query_string, start_time, before, log_group):
        fields = {field["field"]: field["value"] for field in row}
        match = _START_REQUEST_ID_PATTERN.match(fields.get("@message", ""))
        if match is None:
            continue
        parsed = _parse_insights_timestamp(fields.get("@timestamp", ""))
        if parsed is None:
            continue
        boundaries.append((match.group(1), datetime.fromisoformat(parsed).timestamp()))
    return boundaries


def _fetch_runs_page(log_group: str, before: float | None, count: int) -> dict[str, Any]:
    window_end = before if before is not None else time.time()
    boundaries = _run_boundaries(log_group, window_end, count, RUN_LOOKBACK_MINUTES)
    if not boundaries:
        return {"runs": [], "next_cursor": None}

    window_start = min(epoch for _, epoch in boundaries)
    boundary_ids = {request_id for request_id, _ in boundaries}
    query_string = "fields @timestamp, @message | sort @timestamp asc"
    raw_events = [
        _parse_log_event_row(row) for row in _run_insights_query(query_string, window_start, window_end, log_group)
    ]
    events = [event for event in raw_events if event is not None]

    runs = [run for run in _group_log_runs(events) if run["id"] in boundary_ids]
    # -1s so the next page's window strictly excludes this page's oldest run (Insights' endTime is inclusive).
    next_cursor = (window_start - 1) if len(boundaries) == count else None
    return {"runs": runs, "next_cursor": next_cursor}


def _search_log_lines(log_group: str, pattern: str, before: float | None, limit: int) -> dict[str, Any]:
    """Insights `like "literal"` (a plain substring match) rather than `like /regex/`,
    so user input is never interpreted as a regex - avoids both injection risk and
    surprising regex semantics for what's meant to be a plain-text search box."""
    escaped = pattern.replace("\\", "\\\\").replace('"', '\\"')
    query_string = f'fields @timestamp, @message | filter @message like "{escaped}" | sort @timestamp desc | limit {limit}'
    end_time = before if before is not None else time.time()
    start_time = end_time - SEARCH_LOOKBACK_MINUTES * 60
    events = [_parse_log_event_row(row) for row in _run_insights_query(query_string, start_time, end_time, log_group)]
    events = [event for event in events if event is not None]
    oldest_epoch = min((datetime.fromisoformat(e["timestamp"]).timestamp() for e in events), default=None)
    next_cursor = (oldest_epoch - 1) if len(events) == limit and oldest_epoch is not None else None
    return {"events": events, "next_cursor": next_cursor}


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


def _last_invocation_time(log_group: str = WATCH_LOG_GROUP, hours: int = 1) -> str | None:
    """Exact last-invocation timestamp from logs, not a CloudWatch metric bucket
    start (which can be up to one period-width earlier than the real event)."""
    start_time_ms = int((time.time() - hours * 3600) * 1000)
    response = logs_client.filter_log_events(
        logGroupName=log_group,
        startTime=start_time_ms,
        filterPattern="REPORT RequestId",
        interleaved=True,
    )
    events = response.get("events", [])
    if not events:
        return None
    latest_ms = max(event["timestamp"] for event in events)
    return datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).isoformat()


def _duration_series(minutes: int, function_name: str = WATCH_FUNCTION_NAME) -> list[dict[str, Any]]:
    """Per-invocation Duration - period scales with the selected window (see
    _metric_period_seconds) rather than a fixed 300s, so a 5-minute window
    still gets real points and a week-long window doesn't balloon into
    thousands of them."""
    end_time = time.time()
    start_time = end_time - minutes * 60
    period = _metric_period_seconds(int(end_time - start_time))
    response = cloudwatch_client.get_metric_data(
        MetricDataQueries=[_metric_query("duration_series", period, "AWS/Lambda", "Duration", "Average", function_name)],
        StartTime=start_time,
        EndTime=end_time,
        ScanBy="TimestampAscending",
    )
    result = response["MetricDataResults"][0]
    return [
        {"timestamp": timestamp.isoformat(), "value": round(value, 2)}
        for timestamp, value in zip(result["Timestamps"], result["Values"])
    ]


def _report_line_stats(log_group: str, start_time: float, end_time: float) -> dict[str, Any]:
    """Cold-start rate, memory headroom, and p95 duration - none of these are exposed
    by CloudWatch's Lambda metrics (GetMetricData has no MemoryUtilization/cold-start
    metric), but every invocation's own REPORT line already carries them, so one
    Insights query with `parse`+`stats` pulls them out server-side instead of hauling
    every raw REPORT line back to Python."""
    query_string = (
        "fields @message"
        " | filter @message like /^REPORT RequestId/"
        r" | parse @message /Duration: (?<duration_ms>[\d.]+) ms/"
        r" | parse @message /Memory Size: (?<memory_size_mb>\d+) MB/"
        r" | parse @message /Max Memory Used: (?<memory_used_mb>\d+) MB/"
        r" | parse @message /Init Duration: (?<init_duration_ms>[\d.]+) ms/"
        " | stats count() as total_count, count(init_duration_ms) as cold_start_count,"
        " avg(memory_used_mb) as avg_memory_used_mb, max(memory_size_mb) as configured_memory_mb,"
        " pct(duration_ms, 95) as p95_duration_ms"
    )
    rows = _run_insights_query(query_string, start_time, end_time, log_group)
    if not rows:
        return {"cold_start_rate": None, "avg_memory_used_mb": None, "memory_size_mb": None, "p95_duration_ms": None}
    fields = {field["field"]: field["value"] for field in rows[0]}
    total_count = int(float(fields.get("total_count", 0)))
    cold_start_count = int(float(fields.get("cold_start_count", 0)))
    return {
        "cold_start_rate": round(cold_start_count / total_count, 4) if total_count else None,
        "avg_memory_used_mb": round(float(fields["avg_memory_used_mb"]), 1) if fields.get("avg_memory_used_mb") else None,
        "memory_size_mb": round(float(fields["configured_memory_mb"])) if fields.get("configured_memory_mb") else None,
        "p95_duration_ms": round(float(fields["p95_duration_ms"]), 1) if fields.get("p95_duration_ms") else None,
    }


LOG_QUERY_POLL_INTERVAL_SECONDS = 0.5
# 15s budget - the log group's total volume (and so Insights scan time) grows as
# watch.py keeps running, and the observed tail has been creeping toward the old
# 10s cap; this stays comfortably under API Gateway's 30s integration timeout.
LOG_QUERY_MAX_POLLS = 30
INSIGHTS_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"

# Selectable time ranges for the metrics page - values are minutes. A fixed
# lookup rather than an arbitrary user-supplied number, since this all feeds
# straight into CloudWatch/Insights query windows.
METRICS_RANGE_PRESETS_MINUTES = {
    "5m": 5, "10m": 10, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "3h": 180, "6h": 360, "12h": 720,
    "24h": 1440, "2d": 2880, "3d": 4320, "1w": 10080,
}
DEFAULT_METRICS_RANGE = "24h"

DEFAULT_RUNS_PAGE_SIZE = 5
RUN_LOOKBACK_MINUTES = METRICS_RANGE_PRESETS_MINUTES["1w"]
SEARCH_PAGE_LIMIT = 200
SEARCH_LOOKBACK_MINUTES = METRICS_RANGE_PRESETS_MINUTES["1w"]
LLM_LOG_PAGE_LIMIT = 50


def _metric_period_seconds(window_seconds: int) -> int:
    """Picks a CloudWatch period that keeps a time-series query to a sane number
    of datapoints (~300) regardless of the selected window - a fixed 300s period
    was fine back when the window was always a hardcoded 24h, but would give a
    single partial bucket for a 5-minute window and thousands of points for a week."""
    for period in (60, 300, 900, 1800, 3600, 21600, 86400):
        if window_seconds / period <= 300:
            return period
    return 86400


_BIN_SECONDS_TO_EXPRESSION = {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h", 21600: "6h", 86400: "1d"}


def _insights_bin_seconds(window_seconds: int) -> int:
    """Same idea as _metric_period_seconds, but for Insights' bin() syntax."""
    for seconds in _BIN_SECONDS_TO_EXPRESSION:
        if window_seconds / seconds <= 200:
            return seconds
    return 86400


def _insights_bin_expression(window_seconds: int) -> str:
    return _BIN_SECONDS_TO_EXPRESSION[_insights_bin_seconds(window_seconds)]


def _run_insights_query(
    query_string: str, start_time: float, end_time: float, log_group: str = WATCH_LOG_GROUP
) -> list[list[dict[str, str]]]:
    """Runs a CloudWatch Logs Insights query to completion (or gives up after
    LOG_QUERY_MAX_POLLS) and returns its raw result rows - each row a list of
    {field, value} dicts, same shape boto3 returns from get_query_results."""
    query_id = logs_client.start_query(
        logGroupName=log_group,
        startTime=int(start_time),
        endTime=int(end_time),
        queryString=query_string,
    )["queryId"]

    result: dict[str, Any] = {"status": "Timeout", "results": []}
    for _ in range(LOG_QUERY_MAX_POLLS):
        result = logs_client.get_query_results(queryId=query_id)
        if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(LOG_QUERY_POLL_INTERVAL_SECONDS)
    return result["results"] if result["status"] == "Complete" else []


def _parse_insights_timestamp(raw_timestamp: str) -> str | None:
    try:
        return datetime.strptime(raw_timestamp, INSIGHTS_TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _structured_log_series(event_name: str, minutes: int, log_group: str = WATCH_LOG_GROUP) -> list[dict[str, Any]]:
    """Parses watch.py's `print(json.dumps({"event": event_name, ...}))` lines
    into per-run data points, via CloudWatch Logs Insights rather than
    FilterLogEvents - Insights is indexed and sorts server-side, where
    FilterLogEvents can return an empty page with nextToken still set (a
    single call finishing with zero events does NOT mean there are no matches,
    only that it gave up scanning before finding one), which was silently
    returning empty series despite real matches existing.

    limit scales with the window - watch.py runs roughly every 5 minutes, so a
    week-long window could have ~2000 matching runs; a fixed small limit would
    silently truncate a longer window down to just its most recent slice.
    """
    limit = min(5000, max(200, minutes // 5 + 100))
    query_string = f"fields @timestamp, @message | filter @message like /{event_name}/ | sort @timestamp desc | limit {limit}"
    end_time = time.time()
    start_time = end_time - minutes * 60
    parsed: list[dict[str, Any]] = []
    for row in _run_insights_query(query_string, start_time, end_time, log_group):
        fields = {field["field"]: field["value"] for field in row}
        try:
            payload = json.loads(fields.get("@message", ""))
        except json.JSONDecodeError:
            continue
        if payload.get("event") != event_name:
            continue
        timestamp = _parse_insights_timestamp(fields.get("@timestamp", ""))
        if timestamp is None:
            continue
        payload["timestamp"] = timestamp
        parsed.append(payload)
    parsed.sort(key=lambda item: item["timestamp"])
    return parsed


def _token_usage_series(minutes: int) -> list[dict[str, Any]]:
    """Sums classifier_call/validity_check token usage into time buckets sized
    to the selected window (see _insights_bin_expression) - both event types
    already log input_tokens/output_tokens per OpenRouter call (see llm.py),
    this just aggregates them server-side via Insights instead of pulling every
    individual call's tokens back to sum in Python.

    Insights' `stats ... by bin()` only returns buckets that actually matched
    a row - a bucket with zero LLM activity (common; most 5-minute runs
    find nothing new to classify) is simply absent, not present with a zero.
    Left as-is, Chart.js draws a line connecting only the sparse real points,
    implying a trend across a gap that was actually flat zero the whole time.
    Every bucket in the window is zero-filled here so the series is complete.
    """
    window_seconds = minutes * 60
    bin_seconds = _insights_bin_seconds(window_seconds)
    bin_expression = _BIN_SECONDS_TO_EXPRESSION[bin_seconds]
    end_time = time.time()
    start_time = end_time - window_seconds
    query_string = (
        "fields @timestamp, @message"
        " | filter @message like /classifier_call/ or @message like /validity_check/"
        " | parse @message /\"input_tokens\":\\s*(?<raw_input>\\d+)/"
        " | parse @message /\"output_tokens\":\\s*(?<raw_output>\\d+)/"
        f" | stats sum(raw_input) as input_tokens, sum(raw_output) as output_tokens by bin({bin_expression}) as bucket"
        " | sort bucket asc"
    )
    by_timestamp: dict[str, dict[str, Any]] = {}
    for row in _run_insights_query(query_string, start_time, end_time):
        fields = {field["field"]: field["value"] for field in row}
        timestamp = _parse_insights_timestamp(fields.get("bucket", ""))
        if timestamp is None:
            continue
        by_timestamp[timestamp] = {
            "timestamp": timestamp,
            "input_tokens": int(float(fields.get("input_tokens", 0))),
            "output_tokens": int(float(fields.get("output_tokens", 0))),
        }

    bucket_epoch = int(start_time // bin_seconds) * bin_seconds
    filled: list[dict[str, Any]] = []
    while bucket_epoch <= end_time:
        timestamp = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat()
        filled.append(by_timestamp.get(timestamp, {"timestamp": timestamp, "input_tokens": 0, "output_tokens": 0}))
        bucket_epoch += bin_seconds
    return filled


def _token_usage_by_user(minutes: int) -> list[dict[str, Any]]:
    """Per-user spend from classifier_call only - validity_check is shared/deduplicated across users, not attributable to one. Calls before user_id logging existed fall into "unknown"."""
    query_string = (
        "fields @message"
        " | filter @message like /classifier_call/"
        " | parse @message /\"user_id\":\\s*\"(?<raw_user_id>[^\"]*)\"/"
        " | parse @message /\"input_tokens\":\\s*(?<raw_input>\\d+)/"
        " | parse @message /\"output_tokens\":\\s*(?<raw_output>\\d+)/"
        " | stats sum(raw_input) as input_tokens, sum(raw_output) as output_tokens by raw_user_id"
        " | sort input_tokens desc"
    )
    end_time = time.time()
    start_time = end_time - minutes * 60
    parsed: list[dict[str, Any]] = []
    for row in _run_insights_query(query_string, start_time, end_time):
        fields = {field["field"]: field["value"] for field in row}
        parsed.append(
            {
                "user_id": fields.get("raw_user_id") or "unknown",
                "input_tokens": int(float(fields.get("input_tokens", 0))),
                "output_tokens": int(float(fields.get("output_tokens", 0))),
            }
        )
    return parsed


def _notifications_by_user(minutes: int) -> list[dict[str, Any]]:
    """Each user's notified listings within the window, from DynamoDB. Per-user lookups run concurrently since each is its own full-history scan."""
    since = time.time() - minutes * 60
    user_ids = [str(user["user_id"]) for user in list_all_users()]

    def notifications_for(user_id: str) -> dict[str, Any]:
        notifications = [
            {
                "company_name": item.get("company_name", ""),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "seen_at": item.get("seen_at", 0),
                "fit_score": item.get("fit_score"),
            }
            for item in list_seen_listings(user_id, since=since)
            if item.get("status") == "notified"
        ]
        notifications.sort(key=lambda item: item["seen_at"], reverse=True)
        return {"user_id": user_id, "notifications": notifications}

    if not user_ids:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(user_ids))) as executor:
        return list(executor.map(notifications_for, user_ids))


ADMIN_ACTIVITY_CACHE_TTL_SECONDS = 20
_admin_activity_cache: dict[int, tuple[float, dict[str, Any]]] = {}


def _admin_activity(minutes: int) -> dict[str, Any]:
    now = time.time()
    cached = _admin_activity_cache.get(minutes)
    if cached is not None and now - cached[0] < ADMIN_ACTIVITY_CACHE_TTL_SECONDS:
        return cached[1]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        token_future = executor.submit(_token_usage_by_user, minutes)
        notifications_future = executor.submit(_notifications_by_user, minutes)
        result = {
            "token_usage_by_user": token_future.result(),
            "notifications_by_user": notifications_future.result(),
        }
    _admin_activity_cache[minutes] = (now, result)
    return result


def _invocation_metrics(start_time: float, end_time: float, function_name: str = WATCH_FUNCTION_NAME) -> dict[str, Any]:
    """errors/avg_duration_ms/throttles are single stat-tile numbers for the whole
    selected window, so their period is the window itself (one bucket) - period used to be
    hardcoded to 86400 (24h), which only happened to be correct because the window
    was always a hardcoded 24h too; it must track the actual window now that it's
    selectable, or a query_id's "latest" value would silently only reflect its last
    sub-bucket instead of the whole range. invocations is summed across whatever
    buckets exist, so it stays correct at any period - it just uses the same
    resolution-scaled period as the other time-series queries for consistency."""
    window_seconds = int(end_time - start_time)
    whole_window_period = max(60, window_seconds)
    series_period = _metric_period_seconds(window_seconds)
    queries = [
        _metric_query("invocations", series_period, "AWS/Lambda", "Invocations", "Sum", function_name),
        _metric_query("errors", whole_window_period, "AWS/Lambda", "Errors", "Sum", function_name),
        _metric_query("avg_duration_ms", whole_window_period, "AWS/Lambda", "Duration", "Average", function_name),
        _metric_query("throttles", whole_window_period, "AWS/Lambda", "Throttles", "Sum", function_name),
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
        "invocations": round(sum(invocation_values), 2),
        "errors": latest("errors"),
        "avg_duration_ms": latest("avg_duration_ms"),
        "throttles": latest("throttles"),
    }


def _source_health_summary() -> dict[str, int]:
    """Reduces the existing source-health scan (list_source_health, already used by
    /api/admin/source-health) into a healthy/unhealthy rollup, using the same
    consecutive-failure threshold watch.py already alerts on - no new DynamoDB writes."""
    rows = list_source_health()
    unhealthy = sum(1 for row in rows if int(row.get("consecutive_failures", 0)) >= SOURCE_FAILURE_ALERT_THRESHOLD)
    return {"healthy_count": len(rows) - unhealthy, "unhealthy_count": unhealthy}


def _zyte_call_count(minutes: int) -> int:
    """Zyte is billed per request - counted from watch.py's source_fetch events
    (which already carry `kind` per source) rather than a separate cost-tracking
    mechanism. A count() query, not full payload parsing - source_fetch fires once
    per source per run, which is too high-volume to parse every row over a long window."""
    query_string = (
        'fields @message | filter @message like /"event":\\s*"source_fetch"/'
        ' and @message like /"kind":\\s*"zyte"/ | stats count() as total'
    )
    end_time = time.time()
    start_time = end_time - minutes * 60
    rows = _run_insights_query(query_string, start_time, end_time, WATCH_LOG_GROUP)
    if not rows:
        return 0
    fields = {field["field"]: field["value"] for field in rows[0]}
    return int(float(fields.get("total", 0)))


def _render_series(minutes: int) -> list[dict[str, Any]]:
    """Buckets renderer's render_success/render_failure events, zero-filled the same
    way _token_usage_series is. totalMs only exists on render_success events, so
    count(total_ms) is a free success count - Insights' stats functions have no
    general if()/case(), so this avoids needing a conditional aggregation."""
    window_seconds = minutes * 60
    bin_seconds = _insights_bin_seconds(window_seconds)
    bin_expression = _BIN_SECONDS_TO_EXPRESSION[bin_seconds]
    end_time = time.time()
    start_time = end_time - window_seconds
    query_string = (
        "fields @timestamp, @message"
        ' | filter @message like /"event":\\s*"render_success"/ or @message like /"event":\\s*"render_failure"/'
        r' | parse @message /"totalMs":\s*(?<total_ms>\d+)/'
        " | stats count() as total_count, count(total_ms) as success_count, avg(total_ms) as avg_total_ms"
        f" by bin({bin_expression}) as bucket"
        " | sort bucket asc"
    )
    by_timestamp: dict[str, dict[str, Any]] = {}
    for row in _run_insights_query(query_string, start_time, end_time, RENDERER_LOG_GROUP):
        fields = {field["field"]: field["value"] for field in row}
        timestamp = _parse_insights_timestamp(fields.get("bucket", ""))
        if timestamp is None:
            continue
        total_count = int(float(fields.get("total_count", 0)))
        success_count = int(float(fields.get("success_count", 0)))
        by_timestamp[timestamp] = {
            "timestamp": timestamp,
            "success_count": success_count,
            "failure_count": total_count - success_count,
            "avg_total_ms": round(float(fields["avg_total_ms"]), 1) if fields.get("avg_total_ms") else None,
        }

    bucket_epoch = int(start_time // bin_seconds) * bin_seconds
    filled: list[dict[str, Any]] = []
    while bucket_epoch <= end_time:
        timestamp = datetime.fromtimestamp(bucket_epoch, tz=timezone.utc).isoformat()
        filled.append(
            by_timestamp.get(
                timestamp, {"timestamp": timestamp, "success_count": 0, "failure_count": 0, "avg_total_ms": None}
            )
        )
        bucket_epoch += bin_seconds
    return filled


def _auth_rejected_count(minutes: int) -> int:
    """Login rate-limit rejections - _is_rate_limited/_record_failed_auth already
    exist but were invisible until now; a simple count is enough to flag brute-forcing."""
    query_string = 'fields @message | filter @message like /"event":\\s*"auth_rejected"/ | stats count() as total'
    end_time = time.time()
    start_time = end_time - minutes * 60
    rows = _run_insights_query(query_string, start_time, end_time, DASHBOARD_LOG_GROUP)
    if not rows:
        return 0
    fields = {field["field"]: field["value"] for field in rows[0]}
    return int(float(fields.get("total", 0)))


METRICS_CACHE_TTL_SECONDS = 20
_metrics_cache: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}


def _recent_metrics(minutes: int = 1440, lambda_key: str = DEFAULT_LAMBDA_KEY) -> dict[str, Any]:
    """Cached in-process for METRICS_CACHE_TTL_SECONDS, keyed by the selected
    window - the Metrics page polls this every 60s, and the underlying CloudWatch
    Logs Insights queries can each take several seconds against a growing log
    group, so re-running the full fetch on every single request (auto-refresh,
    multiple admins, page reloads) was doing a lot of redundant expensive work
    for data that barely changes that often. Best-effort only (per warm Lambda
    container, not a shared cache), which is fine here - the downside of a miss
    is just falling back to today's latency.
    """
    now = time.time()
    cache_key = (minutes, lambda_key)
    cached = _metrics_cache.get(cache_key)
    if cached is not None and now - cached[0] < METRICS_CACHE_TTL_SECONDS:
        return cached[1]

    end_time = now
    start_time = end_time - minutes * 60
    function_name = LAMBDA_FUNCTION_NAMES.get(lambda_key, WATCH_FUNCTION_NAME)
    log_group = LOG_GROUPS_BY_LAMBDA.get(lambda_key, WATCH_LOG_GROUP)

    # Independent CloudWatch/Logs round-trips, dispatched concurrently rather than
    # one after another - filter_log_events scanning a noisy 24h log group for a
    # term with no matches can alone take several seconds, and serializing these
    # back to back is what was making the metrics page painfully slow to load.
    with concurrent.futures.ThreadPoolExecutor(max_workers=9) as executor:
        invocation_metrics_future = executor.submit(_invocation_metrics, start_time, end_time, function_name)
        last_ran_future = executor.submit(_last_invocation_time, log_group)
        duration_series_future = executor.submit(_duration_series, minutes, function_name)
        report_stats_future = executor.submit(_report_line_stats, log_group, start_time, end_time)
        source_health_future = executor.submit(_source_health_summary)
        zyte_calls_future = executor.submit(_zyte_call_count, minutes)

        # Only the selected lambda's own business-logic events make sense to chart -
        # scan_summary/validator_backlog/token usage are watch-only, render outcomes
        # are renderer-only, auth rejections are dashboard-only.
        lambda_specific_futures: dict[str, concurrent.futures.Future[Any]] = {}
        if lambda_key == "watch":
            lambda_specific_futures["throughput_series"] = executor.submit(_structured_log_series, "scan_summary", minutes)
            lambda_specific_futures["backlog_series"] = executor.submit(_structured_log_series, "validator_backlog", minutes)
            lambda_specific_futures["token_usage_series"] = executor.submit(_token_usage_series, minutes)
        elif lambda_key == "renderer":
            lambda_specific_futures["render_series"] = executor.submit(_render_series, minutes)
        elif lambda_key == "dashboard":
            lambda_specific_futures["auth_rejected_count"] = executor.submit(_auth_rejected_count, minutes)

        result = {
            **invocation_metrics_future.result(),
            "last_ran": last_ran_future.result(),
            "duration_series": duration_series_future.result(),
            **report_stats_future.result(),
            "source_health": source_health_future.result(),
            "zyte_calls": zyte_calls_future.result(),
            **{key: future.result() for key, future in lambda_specific_futures.items()},
        }
    _metrics_cache[cache_key] = (now, result)
    return result


def _asset_response(body: bytes, filename: str, cache_control: str) -> dict[str, Any]:
    """Base64 for everything: HTTP APIs decode it, so binary assets cannot silently corrupt."""
    content_type, _ = mimetypes.guess_type(filename)
    return {
        "statusCode": 200,
        "headers": {"content-type": content_type or "application/octet-stream", "cache-control": cache_control},
        "body": base64.b64encode(body).decode("ascii"),
        "isBase64Encoded": True,
    }


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
