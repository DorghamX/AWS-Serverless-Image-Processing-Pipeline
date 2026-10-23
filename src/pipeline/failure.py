"""FailJob catch-all — the Step Functions Catch routes any failure here.

Marks the image FAILED in DynamoDB (with a truncated error cause) and
publishes a failure message to SNS. Always returns normally so the
execution ends cleanly with a Failed workflow status visible in the console.
"""

import json
import logging

from common import publish_notification, set_status

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_CAUSE_CHARS = 500


def lambda_handler(event, context):
    image_id = event.get("imageId", "unknown")
    error = event.get("error", {}) or {}

    cause = error.get("Cause") or json.dumps(error)[:MAX_CAUSE_CHARS]
    if isinstance(cause, str) and len(cause) > MAX_CAUSE_CHARS:
        cause = cause[:MAX_CAUSE_CHARS] + "…"

    set_status(image_id, "FAILED", error=cause, failedAt=_now())
    publish_notification("Image FAILED: " + image_id, {
        "status": "FAILED",
        "imageId": image_id,
        "sourceKey": event.get("key"),
        "error": cause,
    })
    log.error("Job failed for %s: %s", image_id, cause)
    return {"imageId": image_id, "status": "FAILED", "error": cause}


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
