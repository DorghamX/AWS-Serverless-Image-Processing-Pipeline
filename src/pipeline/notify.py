"""NotifySuccess step — publishes a completion summary to the SNS topic."""

import json
import logging
import os

from common import publish_notification

log = logging.getLogger()
log.setLevel(logging.INFO)

STACK_TAG = os.environ.get("AWS_REGION", "aws")


def lambda_handler(event, context):
    image_id = event["imageId"]
    processed = event.get("watermark", {}).get("processed", [])

    message = {
        "status": "COMPLETED",
        "imageId": image_id,
        "sourceKey": event.get("key"),
        "variants": [
            {"variant": v["variant"], "key": v["key"],
             "width": v["width"], "height": v["height"]}
            for v in processed
        ],
    }
    publish_notification("Image processed: " + image_id, message)
    log.info("Published completion notification for %s", image_id)
    return event
