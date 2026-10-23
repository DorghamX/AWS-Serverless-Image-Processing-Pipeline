"""Shared helpers used by every Lambda in the image pipeline."""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

# Initialised at cold start and reused across warm invocations.
_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(os.environ["TABLE_NAME"])
_sns = boto3.client("sns")

# Attribute names that are DynamoDB reserved words need expression aliases.
_RESERVED = {
    "status": "#status",
    "timestamp": "#ts",
    "size": "#size",
    "error": "#err",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_status(image_id: str, status: str, **extra) -> None:
    """Update the metadata item's status (and any extra attributes) in DynamoDB.

    Extra keyword arguments become top-level attributes, e.g.
    set_status("abc", "COMPLETED", processedAt=..., variants=[...]).
    """
    names = {"#status": "status"}
    values = {":status": status}
    updates = ["#status = :status"]
    sets, removes = [], []

    for i, (key, value) in enumerate(sorted(extra.items())):
        name_alias = f"#a{i}"
        value_alias = f":v{i}"
        if value is None:
            removes.append(f"{name_alias}")
            names[name_alias] = key
        else:
            sets.append(f"{name_alias} = {value_alias}")
            names[name_alias] = key
            values[value_alias] = value

    if sets:
        updates.append(" ".join(f"SET {' , '.join(sets)}"))
    if removes:
        updates.append(" ".join(f"REMOVE {' , '.join(removes)}"))
    expression = " ".join(u for u in updates if u)

    kwargs = {
        "Key": {"imageId": image_id},
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }
    try:
        _table.update_item(**kwargs)
    except Exception:  # noqa: BLE001 - never let metadata writes fail the workflow
        log.exception("Failed to update status for image %s", image_id)


def publish_notification(subject: str, message: dict) -> None:
    """Publish a JSON message to the notification SNS topic."""
    _sns.publish(
        TopicArn=os.environ["TOPIC_ARN"],
        Subject=subject[:99],
        Message=json.dumps(message, default=str),
    )
