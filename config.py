from __future__ import annotations

import json

import boto3

CONFIG_PARAMETER_NAME = "/job-alerts/config"

# Companies the "community" source can be filtered to (see sources/community.py)
# and the source kinds build_sources() knows how to construct (see sources/__init__.py).
# Kept here, not in sources/, since the dashboard Lambda packages config.py but not sources/.
SUPPORTED_COMPANIES = ["Google", "Apple", "Tesla", "SpaceX"]
SUPPORTED_SOURCE_KINDS = ["community", "apple", "google"]


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
