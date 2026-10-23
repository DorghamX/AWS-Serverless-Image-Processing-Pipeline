"""SQS -> Step Functions dispatcher.

Lambda's event source mapping delivers batches of SQS messages (each one an
S3 ObjectCreated event published by the source bucket). For every valid S3
record we mark the image QUEUED in DynamoDB and start one Step Functions
execution. Failed messages are retried by the queue redrive policy and
eventually land in the DLQ.
"""

import json
import logging
import os
import urllib.parse
import uuid

import boto3

from common import set_status

log = logging.getLogger()
log.setLevel(logging.INFO)

sfn = boto3.client("stepfunctions")
STATE_MACHINE_ARN = os.environ["STATE_MACHINE_ARN"]

BATCH_ITEM_FAILURES = {"batchItemFailures": []}


def lambda_handler(event, context):
    failed_ids = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        try:
            body = json.loads(record["body"])
            # S3 event notifications are wrapped in a "Records" list.
            for s3_record in body.get("Records", []):
                bucket = s3_record["s3"]["bucket"]["name"]
                key = urllib.parse.unquote_plus(s3_record["s3"]["object"]["key"])
                image_id = image_id_from_key(key)
                size_bytes = s3_record["s3"]["object"].get("size", 0)

                set_status(image_id, "QUEUED", sourceBucket=bucket, sourceKey=key,
                           uploadedAt=body.get("time"))

                sfn.start_execution(
                    stateMachineArn=STATE_MACHINE_ARN,
                    # Execution names must be unique; keep them short (< 80 chars).
                    name=f"{image_id[:40]}-{uuid.uuid4().hex[:12]}",
                    input=json.dumps({
                        "imageId": image_id,
                        "bucket": bucket,
                        "key": key,
                        "sizeBytes": size_bytes,
                    }),
                )
                log.info("Started execution for %s (%s)", image_id, key)
        except Exception:  # noqa: BLE001
            log.exception("Failed to process message %s", message_id)
            failed_ids.append({"itemIdentifier": message_id})

    # Report partial batch failures so only failed messages get retried.
    return {"batchItemFailures": failed_ids}


def image_id_from_key(key: str) -> str:
    """Keys look like uploads/<imageId>/<filename> — extract the imageId."""
    parts = key.split("/")
    return parts[1] if len(parts) >= 3 else urllib.parse.quote(key, safe="")
