from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import boto3

from config import SUPPORTED_COMPANIES, SUPPORTED_SOURCE_KINDS, load_config, save_config

WATCH_LOG_GROUP = "/aws/lambda/job-alerts-watch"
WATCH_FUNCTION_NAME = "job-alerts-watch"
DASHBOARD_PASSWORD = os.environ["DASHBOARD_PASSWORD"]

logs_client = boto3.client("logs")
cloudwatch_client = boto3.client("cloudwatch")

PAGES = {
    "/metrics": (Path(__file__).parent / "metrics.html").read_text(),
    "/config": (Path(__file__).parent / "config.html").read_text(),
    "/logs": (Path(__file__).parent / "logs.html").read_text(),
}

FAILURE_MARKERS = ("fail", "Fail", "FAIL", "Error", "ERROR", "Traceback")


def handler(event: dict[str, Any], _context: object) -> dict[str, Any]:
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]

    if method == "GET" and path == "/":
        return _redirect("/metrics")
    if method == "GET" and path in PAGES:
        return _response(200, "text/html", PAGES[path])

    headers = {key.lower(): value for key, value in (event.get("headers") or {}).items()}
    if not hmac.compare_digest(headers.get("x-dashboard-password", ""), DASHBOARD_PASSWORD):
        return _json_response(401, {"error": "unauthorized"})

    if method == "GET" and path == "/api/options":
        return _json_response(200, {"companies": SUPPORTED_COMPANIES, "sources": SUPPORTED_SOURCE_KINDS})
    if method == "GET" and path == "/api/config":
        return _json_response(200, load_config())
    if method == "PUT" and path == "/api/config":
        save_config(json.loads(event.get("body") or "{}"))
        return _json_response(200, {"status": "saved"})
    if method == "GET" and path == "/api/logs":
        return _json_response(200, {"events": _recent_log_events()})
    if method == "GET" and path == "/api/metrics":
        return _json_response(200, _recent_metrics())

    return _json_response(404, {"error": "not found"})


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


def _recent_metrics(hours: int = 24) -> dict[str, Any]:
    end_time = time.time()
    start_time = end_time - hours * 3600
    queries = [
        _metric_query("invocations", 300, "AWS/Lambda", "Invocations", "Sum", WATCH_FUNCTION_NAME),
        _metric_query("errors", 86400, "AWS/Lambda", "Errors", "Sum", WATCH_FUNCTION_NAME),
        _metric_query("avg_duration_ms", 86400, "AWS/Lambda", "Duration", "Average", WATCH_FUNCTION_NAME),
        _metric_query("notifications_sent", 86400, "job-alerts", "NotificationsSent", "Sum", None),
        _metric_query("classifier_calls", 86400, "job-alerts", "ClassifierCalls", "Sum", None),
        _metric_query("avg_input_tokens", 86400, "job-alerts", "ClassifierInputTokens", "Average", None),
        _metric_query("avg_output_tokens", 86400, "job-alerts", "ClassifierOutputTokens", "Average", None),
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
    invocation_timestamps = by_id["invocations"]["Timestamps"]
    return {
        "invocations_24h": round(sum(invocation_values), 2),
        "last_ran": invocation_timestamps[0].isoformat() if invocation_timestamps else None,
        "errors_24h": latest("errors"),
        "avg_duration_ms": latest("avg_duration_ms"),
        "notifications_sent_24h": latest("notifications_sent"),
        "classifier_calls_24h": latest("classifier_calls"),
        "avg_input_tokens": latest("avg_input_tokens"),
        "avg_output_tokens": latest("avg_output_tokens"),
    }


def _redirect(location: str) -> dict[str, Any]:
    return {"statusCode": 302, "headers": {"location": location}, "body": ""}


def _json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return _response(status_code, "application/json", json.dumps(body))


def _response(status_code: int, content_type: str, body: str) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": content_type},
        "body": body,
    }
