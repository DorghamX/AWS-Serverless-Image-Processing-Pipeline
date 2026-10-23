"""API Gateway (HTTP API) endpoint: POST /images/presign

Request body (JSON):
    { "filename": "holiday.jpg", "contentType": "image/jpeg" }

Response:
    { "imageId": "...", "key": "uploads/<id>/<filename>", "uploadUrl": "https://..." }

The client PUTs the raw image bytes to `uploadUrl`; the upload itself triggers
the S3 -> SQS -> Step Functions pipeline. A metadata item is created up front
with status INITIATED so every image has a traceable record.
"""

import json
import logging
import os
import re
import uuid

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["TABLE_NAME"])
SOURCE_BUCKET = os.environ["SOURCE_BUCKET"]

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
PRESIGN_TTL_SECONDS = 600
MAX_FILENAME_LEN = 100
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")


def lambda_handler(event, context):
    body = {}
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"message": "Body must be valid JSON"})

    filename = _sanitize_filename(str(body.get("filename", "image.jpg")))
    content_type = body.get("contentType", "image/jpeg")

    if content_type not in ALLOWED_CONTENT_TYPES:
        return _response(415, {
            "message": f"Unsupported contentType. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}"
        })

    image_id = str(uuid.uuid4())
    key = f"uploads/{image_id}/{filename}"

    table.put_item(Item={
        "imageId": image_id,
        "status": "INITIATED",
        "filename": filename,
        "contentType": content_type,
        "sourceKey": key,
        "createdAt": _now(),
    })

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": SOURCE_BUCKET, "Key": key,
                "ContentType": content_type},
        ExpiresIn=PRESIGN_TTL_SECONDS,
    )

    log.info("Issued pre-signed URL for %s (%s)", image_id, key)
    return _response(200, {"imageId": image_id, "key": key, "uploadUrl": upload_url})


def _sanitize_filename(name: str) -> str:
    name = name.split("/")[-1].split("\\")[-1]
    name = SAFE_FILENAME.sub("_", name).lstrip(".") or "image.jpg"
    return name[:MAX_FILENAME_LEN]


def _response(status: int, payload: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
