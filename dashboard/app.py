from __future__ import annotations

import base64
import io
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError
from pypdf import PdfReader

from classifier import ClassifierError, is_good_fit
from config import SUPPORTED_JOB_TYPES, SUPPORTED_SOURCE_KINDS
from sources.base import Listing
from users import (
    create_user,
    current_month_usage,
    delete_company,
    delete_user,
    delete_user_resume,
    find_user_by_api_key,
    generate_api_key,
    get_user,
    increment_usage,
    list_all_users,
    list_companies,
    list_seen_listings,
    list_source_health,
    load_user_config,
    load_user_profile,
    retry_listing,
    save_company,
    save_user_config,
    save_user_profile,
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

PAGES = {
    "/metrics": (Path(__file__).parent / "metrics.html").read_text(),
    "/listings": (Path(__file__).parent / "listings.html").read_text(),
    "/config": (Path(__file__).parent / "config.html").read_text(),
    "/logs": (Path(__file__).parent / "logs.html").read_text(),
    "/admin": (Path(__file__).parent / "admin.html").read_text(),
    "/sources": (Path(__file__).parent / "sources.html").read_text(),
    "/profile": (Path(__file__).parent / "profile.html").read_text(),
}

FAILURE_MARKERS = ("fail", "Fail", "FAIL", "Error", "ERROR", "Traceback")
MAX_RESUME_UPLOAD_BYTES = 5 * 1024 * 1024
RESUME_TEXT_CHAR_CAP = 6000
# ponytail: resume_text gets resent on every single per-listing classifier
# call, so it's capped here (once, at upload time) rather than left unbounded -
# protects downstream token cost regardless of how long the source PDF is.


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]

    if method == "GET" and path == "/":
        return _redirect("/metrics")
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
        return _json_response(200, {"user_id": user_id, "is_admin": is_admin})
    if method == "GET" and path == "/api/options":
        company_names = [str(entry["company_name"]) for entry in list_companies()]
        return _json_response(
            200, {"companies": company_names, "sources": SUPPORTED_SOURCE_KINDS, "job_types": SUPPORTED_JOB_TYPES}
        )
    if method == "GET" and path == "/api/config":
        return _json_response(200, load_user_config(user_id))
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
        return _json_response(200, _recent_metrics(user_id))
    if method == "POST" and path == "/api/apikey":
        return _json_response(200, {"api_key": generate_api_key(user_id)})
    if method == "GET" and path == "/api/listings":
        return _json_response(200, {"listings": list_seen_listings(user_id)})
    if method == "DELETE" and path.startswith("/api/listings/"):
        retry_listing(user_id, path[len("/api/listings/") :])
        return _json_response(200, {"status": "removed"})
    if method == "POST" and path == "/api/test-classifier":
        return _handle_test_classifier(user_id, json.loads(event.get("body") or "{}"))
    if method == "GET" and path == "/api/profile":
        return _json_response(200, load_user_profile(user_id))
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
    classifier_model = str(body.get("classifier_model", ""))
    if not fit_prompt or not classifier_model:
        return _json_response(400, {"error": "fit_prompt and classifier_model are required"})
    sample = Listing(
        source="test",
        id="test",
        company_name=str(body.get("company_name", "")),
        title=str(body.get("title", "")),
        locations=[loc.strip() for loc in str(body.get("locations", "")).split(",") if loc.strip()],
        url="",
        description=str(body.get("description", "")) or None,
    )
    resume_text = str(load_user_profile(user_id).get("resume_text", "")) or None
    increment_usage(user_id)
    try:
        result = is_good_fit(OPENROUTER_API_KEY, classifier_model, fit_prompt, sample, resume_text)
    except ClassifierError as error:
        return _json_response(502, {"error": str(error)})
    return _json_response(200, {"fits": result.fits, "reason": result.reason, "fit_score": result.fit_score})


def _extract_resume_text(pdf_bytes: bytes) -> str:
    """Raises ValueError with a user-facing message on any failure."""
    if len(pdf_bytes) > MAX_RESUME_UPLOAD_BYTES:
        raise ValueError("resume must be under 5MB")
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        resume_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as error:
        raise ValueError("could not parse PDF") from error
    if not resume_text:
        raise ValueError("no extractable text found in PDF")
    return resume_text[:RESUME_TEXT_CHAR_CAP]


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
        resume_text = _extract_resume_text(pdf_bytes)
    except ValueError as error:
        return _json_response(400, {"error": str(error)})

    save_user_profile(user_id, resume_text=resume_text, resume_filename=filename)
    return _json_response(200, load_user_profile(user_id))


def _handle_resume_url_fetch(user_id: str, body: dict[str, Any]) -> dict[str, Any]:
    url = str(body.get("url", "")).strip()
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.netloc:
        return _json_response(400, {"error": "a valid http(s) url is required"})

    request = urllib.request.Request(url, headers={"User-Agent": "job-alerts-dashboard"})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            # Read one byte past the cap so an oversized file is still rejected
            # by _extract_resume_text's own check rather than silently truncated.
            pdf_bytes = response.read(MAX_RESUME_UPLOAD_BYTES + 1)
    except (urllib.error.URLError, TimeoutError) as error:
        return _json_response(400, {"error": f"could not fetch url: {error}"})

    try:
        resume_text = _extract_resume_text(pdf_bytes)
    except ValueError as error:
        return _json_response(400, {"error": str(error)})

    filename = parsed_url.path.rsplit("/", 1)[-1] or "resume.pdf"
    save_user_profile(user_id, resume_text=resume_text, resume_filename=filename, resume_url=url)
    return _json_response(200, load_user_profile(user_id))


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
            user["monthly_classifier_calls"] = current_month_usage(str(user["user_id"]))
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
            "expires_at": {"N": str(now + 3600)},
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


def _recent_metrics(user_id: str, hours: int = 24) -> dict[str, Any]:
    end_time = time.time()
    start_time = end_time - hours * 3600
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
        "last_ran": _last_invocation_time(),
        "errors_24h": latest("errors"),
        "avg_duration_ms": latest("avg_duration_ms"),
        "classifier_calls_this_month": current_month_usage(user_id),
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
