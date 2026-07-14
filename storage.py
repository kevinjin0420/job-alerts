from __future__ import annotations

import json
import os

import boto3
from botocore.exceptions import ClientError

STATE_KEY = "seen.json"
_NOT_FOUND_CODES = {"404", "NoSuchKey"}


def _bucket_name() -> str:
    bucket = os.environ.get("STATE_BUCKET")
    if not bucket:
        raise RuntimeError("STATE_BUCKET environment variable is not set")
    return bucket


def _s3():
    return boto3.client("s3")


def seen_file_exists() -> bool:
    try:
        _s3().head_object(Bucket=_bucket_name(), Key=STATE_KEY)
        return True
    except ClientError as error:
        if error.response["Error"]["Code"] in _NOT_FOUND_CODES:
            return False
        raise


def load_seen_ids() -> set[str]:
    try:
        body = _s3().get_object(Bucket=_bucket_name(), Key=STATE_KEY)["Body"].read()
    except ClientError as error:
        if error.response["Error"]["Code"] in _NOT_FOUND_CODES:
            return set()
        raise
    try:
        return set(json.loads(body))
    except (json.JSONDecodeError, ValueError):
        return set()


def save_seen_ids(seen_ids: set[str]) -> None:
    body = (json.dumps(sorted(seen_ids), indent=2) + "\n").encode("utf-8")
    _s3().put_object(Bucket=_bucket_name(), Key=STATE_KEY, Body=body, ContentType="application/json")
