from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

import boto3
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from sources.base import Listing

USERS_TABLE = "job-alerts-users"
USER_CONFIG_TABLE = "job-alerts-user-config"
SEEN_LISTINGS_TABLE = "job-alerts-seen-listings"
COMPANIES_TABLE = "job-alerts-companies"
SOURCE_HEALTH_TABLE = "job-alerts-source-health"
USER_PROFILE_TABLE = "job-alerts-user-profile"
SETTINGS_TABLE = "job-alerts-settings"
LISTING_VALIDITY_TABLE = "job-alerts-listing-validity"
DEFAULT_CLASSIFIER_MODEL = "qwen/qwen3.6-flash"

_dynamodb = boto3.client("dynamodb")
_deserializer = TypeDeserializer()
_serializer = TypeSerializer()


def _unwrap_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _deserializer.deserialize(value) for key, value in item.items()}


def _wrap_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: _serializer.serialize(value) for key, value in item.items()}



def list_active_users() -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "TableName": USERS_TABLE,
        "FilterExpression": "active = :true",
        "ExpressionAttributeValues": {":true": {"BOOL": True}},
    }
    while True:
        response = _dynamodb.scan(**kwargs)
        users.extend(_unwrap_item(item) for item in response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return users
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def load_user_config(user_id: str) -> dict[str, Any]:
    response = _dynamodb.get_item(TableName=USER_CONFIG_TABLE, Key={"user_id": {"S": user_id}})
    item = response.get("Item")
    return _unwrap_item(item) if item else {}


def load_seen_ids(user_id: str) -> set[str]:
    seen: set[str] = set()
    kwargs: dict[str, Any] = {
        "TableName": SEEN_LISTINGS_TABLE,
        "KeyConditionExpression": "user_id = :u",
        "ExpressionAttributeValues": {":u": {"S": user_id}},
        "ProjectionExpression": "listing_id",
    }
    while True:
        response = _dynamodb.query(**kwargs)
        seen.update(item["listing_id"]["S"] for item in response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return seen
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def record_listings(user_id: str, entries: list[tuple[Listing, str, str, int | None]]) -> None:
    """entries are (listing, status, reason, fit_score). status is 'notified',
    'dismissed', 'invalid' (scraped junk, not an actual job posting), or 'seeded'.
    fit_score is None unless the user has a resume uploaded (see classifier.is_good_fit)."""
    now = int(time.time())
    for listing, status, reason, fit_score in entries:
        item: dict[str, Any] = {
            "user_id": {"S": user_id},
            "listing_id": {"S": listing.unique_id},
            "seen_at": {"N": str(now)},
            "status": {"S": status},
            "reason": {"S": reason},
            "company_name": {"S": listing.company_name},
            "title": {"S": listing.title},
            "url": {"S": listing.url},
            "source": {"S": listing.source},
        }
        if fit_score is not None:
            item["fit_score"] = {"N": str(fit_score)}
        _dynamodb.put_item(TableName=SEEN_LISTINGS_TABLE, Item=item)


def list_seen_listings(user_id: str, limit: int = 300) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "TableName": SEEN_LISTINGS_TABLE,
        "KeyConditionExpression": "user_id = :u",
        "ExpressionAttributeValues": {":u": {"S": user_id}},
    }
    while True:
        response = _dynamodb.query(**kwargs)
        items.extend(_unwrap_item(item) for item in response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            break
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
    items.sort(key=lambda item: item.get("seen_at", 0), reverse=True)
    return items[:limit]


def retry_listing(user_id: str, listing_id: str) -> None:
    """Removes a listing from the seen set so the next run reclassifies it."""
    _dynamodb.delete_item(TableName=SEEN_LISTINGS_TABLE, Key={"user_id": {"S": user_id}, "listing_id": {"S": listing_id}})


def get_listing_validity(listing_id: str) -> dict[str, Any] | None:
    """Whether a listing is a real job posting vs. scraped page furniture - an
    objective fact about the listing, cached once here rather than recomputed
    per user (see classifier.check_is_job_posting)."""
    response = _dynamodb.get_item(TableName=LISTING_VALIDITY_TABLE, Key={"listing_id": {"S": listing_id}})
    item = response.get("Item")
    return _unwrap_item(item) if item else None


def save_listing_validity(listing_id: str, *, is_job_posting: bool, reason: str) -> None:
    _dynamodb.put_item(
        TableName=LISTING_VALIDITY_TABLE,
        Item=_wrap_item(
            {
                "listing_id": listing_id,
                "is_job_posting": is_job_posting,
                "reason": reason,
                "checked_at": int(time.time()),
            }
        ),
    )


def list_all_users() -> list[dict[str, Any]]:
    users: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"TableName": USERS_TABLE}
    while True:
        response = _dynamodb.scan(**kwargs)
        users.extend(_unwrap_item(item) for item in response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return users
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def get_user(user_id: str) -> dict[str, Any] | None:
    response = _dynamodb.get_item(TableName=USERS_TABLE, Key={"user_id": {"S": user_id}})
    item = response.get("Item")
    return _unwrap_item(item) if item else None


def save_ntfy_topic(user_id: str, ntfy_topic: str) -> None:
    _dynamodb.update_item(
        TableName=USERS_TABLE,
        Key={"user_id": {"S": user_id}},
        UpdateExpression="SET ntfy_topic = :t",
        ExpressionAttributeValues={":t": {"S": ntfy_topic}},
    )


def set_user_active(user_id: str, active: bool) -> None:
    """active=False excludes the user from list_active_users, so watch.py skips them without deleting anything."""
    _dynamodb.update_item(
        TableName=USERS_TABLE,
        Key={"user_id": {"S": user_id}},
        UpdateExpression="SET active = :a",
        ExpressionAttributeValues={":a": {"BOOL": active}},
    )


def complete_onboarding(user_id: str) -> None:
    _dynamodb.update_item(
        TableName=USERS_TABLE,
        Key={"user_id": {"S": user_id}},
        UpdateExpression="SET onboarding_completed = :true",
        ExpressionAttributeValues={":true": {"BOOL": True}},
    )


def save_user_config(user_id: str, config: dict[str, Any]) -> None:
    item = dict(config)
    item["user_id"] = user_id
    _dynamodb.put_item(TableName=USER_CONFIG_TABLE, Item=_wrap_item(item))


def create_user(user_id: str, *, is_admin: bool, ntfy_topic: str) -> None:
    _dynamodb.put_item(
        TableName=USERS_TABLE,
        Item=_wrap_item(
            {
                "user_id": user_id,
                "email": user_id,
                "is_admin": is_admin,
                "ntfy_topic": ntfy_topic,
                "active": True,
                "created_at": int(time.time()),
                "onboarding_completed": False,
            }
        ),
    )
    save_user_config(
        user_id,
        {
            "fit_prompt": "",
            "companies": [],
            "job_types": ["intern"],
            "email_to": [user_id],
        },
    )


def delete_user(user_id: str) -> None:
    _dynamodb.delete_item(TableName=USERS_TABLE, Key={"user_id": {"S": user_id}})
    _dynamodb.delete_item(TableName=USER_CONFIG_TABLE, Key={"user_id": {"S": user_id}})
    _dynamodb.delete_item(TableName=USER_PROFILE_TABLE, Key={"user_id": {"S": user_id}})

    for listing_id in load_seen_ids(user_id):
        _dynamodb.delete_item(
            TableName=SEEN_LISTINGS_TABLE, Key={"user_id": {"S": user_id}, "listing_id": {"S": listing_id}}
        )


def generate_api_key(user_id: str) -> str:
    """Overwrites any existing key for this user, invalidating it."""
    token = secrets.token_hex(32)
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    _dynamodb.update_item(
        TableName=USERS_TABLE,
        Key={"user_id": {"S": user_id}},
        UpdateExpression="SET api_key_hash = :h",
        ExpressionAttributeValues={":h": {"S": key_hash}},
    )
    return token


def find_user_by_api_key(token: str) -> dict[str, Any] | None:
    key_hash = hashlib.sha256(token.encode()).hexdigest()
    response = _dynamodb.scan(
        TableName=USERS_TABLE,
        FilterExpression="api_key_hash = :h",
        ExpressionAttributeValues={":h": {"S": key_hash}},
    )
    items = response.get("Items", [])
    return _unwrap_item(items[0]) if items else None


def list_companies() -> list[dict[str, Any]]:
    companies: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"TableName": COMPANIES_TABLE}
    while True:
        response = _dynamodb.scan(**kwargs)
        companies.extend(_unwrap_item(item) for item in response.get("Items", []))
        if "LastEvaluatedKey" not in response:
            return companies
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def save_company(
    name: str,
    source_kind: str,
    added_by: str,
    *,
    board_token: str | None = None,
    board_name: str | None = None,
    intern_url: str | None = None,
    newgrad_url: str | None = None,
    fulltime_url: str | None = None,
) -> None:
    item: dict[str, Any] = {
        "company_name": name,
        "source_kind": source_kind,
        "added_by": added_by,
        "created_at": int(time.time()),
    }
    for key, value in (
        ("board_token", board_token),
        ("board_name", board_name),
        ("intern_url", intern_url),
        ("newgrad_url", newgrad_url),
        ("fulltime_url", fulltime_url),
    ):
        if value:
            item[key] = value
    _dynamodb.put_item(TableName=COMPANIES_TABLE, Item=_wrap_item(item))


def delete_company(name: str) -> None:
    _dynamodb.delete_item(TableName=COMPANIES_TABLE, Key={"company_name": {"S": name}})


def record_source_success(source_name: str) -> None:
    # update_item (not put_item) so last_failure_at/failure_count survive a
    # success instead of being silently dropped by a full-item overwrite.
    _dynamodb.update_item(
        TableName=SOURCE_HEALTH_TABLE,
        Key={"source_name": {"S": source_name}},
        UpdateExpression="SET last_success_at = :now, consecutive_failures = :zero, alerted = :false ADD success_count :one",
        ExpressionAttributeValues={
            ":now": {"N": str(int(time.time()))},
            ":zero": {"N": "0"},
            ":false": {"BOOL": False},
            ":one": {"N": "1"},
        },
    )


def record_source_failure(source_name: str) -> int:
    """Returns the new consecutive-failure count."""
    response = _dynamodb.update_item(
        TableName=SOURCE_HEALTH_TABLE,
        Key={"source_name": {"S": source_name}},
        UpdateExpression=(
            "SET last_failure_at = :now, "
            "consecutive_failures = if_not_exists(consecutive_failures, :zero) + :one "
            "ADD failure_count :one"
        ),
        ExpressionAttributeValues={":now": {"N": str(int(time.time()))}, ":zero": {"N": "0"}, ":one": {"N": "1"}},
        ReturnValues="UPDATED_NEW",
    )
    return int(response["Attributes"]["consecutive_failures"]["N"])


def get_source_last_success(source_name: str) -> int | None:
    response = _dynamodb.get_item(TableName=SOURCE_HEALTH_TABLE, Key={"source_name": {"S": source_name}})
    item = response.get("Item")
    return int(item["last_success_at"]["N"]) if item and "last_success_at" in item else None


def is_source_alerted(source_name: str) -> bool:
    response = _dynamodb.get_item(TableName=SOURCE_HEALTH_TABLE, Key={"source_name": {"S": source_name}})
    item = response.get("Item")
    return bool(item["alerted"]["BOOL"]) if item and "alerted" in item else False


def mark_source_alerted(source_name: str) -> None:
    _dynamodb.update_item(
        TableName=SOURCE_HEALTH_TABLE,
        Key={"source_name": {"S": source_name}},
        UpdateExpression="SET alerted = :true",
        ExpressionAttributeValues={":true": {"BOOL": True}},
    )


def list_source_health() -> list[dict[str, Any]]:
    response = _dynamodb.scan(TableName=SOURCE_HEALTH_TABLE)
    return [_unwrap_item(item) for item in response.get("Items", [])]


def get_classifier_model() -> str:
    response = _dynamodb.get_item(TableName=SETTINGS_TABLE, Key={"setting_name": {"S": "classifier_model"}})
    item = response.get("Item")
    return str(item["value"]["S"]) if item and "value" in item else DEFAULT_CLASSIFIER_MODEL


def save_classifier_model(model: str) -> None:
    _dynamodb.put_item(
        TableName=SETTINGS_TABLE, Item={"setting_name": {"S": "classifier_model"}, "value": {"S": model}}
    )


def load_user_profile(user_id: str) -> dict[str, Any]:
    response = _dynamodb.get_item(TableName=USER_PROFILE_TABLE, Key={"user_id": {"S": user_id}})
    item = response.get("Item")
    return _unwrap_item(item) if item else {}


def save_user_profile(
    user_id: str, *, resume_filename: str, resume_text: str | None = None, resume_url: str | None = None
) -> None:
    """Exactly one of resume_text (uploaded file, cached) or resume_url (live
    URL, fetched fresh by every caller - never cached here) should be set."""
    item: dict[str, Any] = {
        "user_id": user_id,
        "resume_filename": resume_filename,
        "resume_uploaded_at": int(time.time()),
    }
    if resume_text:
        item["resume_text"] = resume_text
    if resume_url:
        item["resume_url"] = resume_url
    _dynamodb.put_item(TableName=USER_PROFILE_TABLE, Item=_wrap_item(item))


def delete_user_resume(user_id: str) -> None:
    _dynamodb.delete_item(TableName=USER_PROFILE_TABLE, Key={"user_id": {"S": user_id}})
