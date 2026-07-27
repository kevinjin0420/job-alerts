from __future__ import annotations

import json

import boto3

CONFIG_PARAMETER_NAME = "/job-alerts/config"


def load_config() -> dict[str, object]:
    parameter = boto3.client("ssm").get_parameter(Name=CONFIG_PARAMETER_NAME)
    return json.loads(parameter["Parameter"]["Value"])


def save_config(config: dict[str, object]) -> None:
    boto3.client("ssm").put_parameter(
        Name=CONFIG_PARAMETER_NAME,
        Value=json.dumps(config),
        Type="String",
        Overwrite=True,
    )
