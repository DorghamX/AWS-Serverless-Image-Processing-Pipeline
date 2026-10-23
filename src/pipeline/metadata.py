"""StoreMetadata step — writes the final status and per-variant metadata to
DynamoDB, then passes the summary downstream to the notification step."""

import logging

from common import set_status, utc_now_iso

log = logging.getLogger()
log.setLevel(logging.INFO)


def lambda_handler(event, context):
    image_id = event["imageId"]
    watermark = event.get("watermark", {})
    processed = watermark.get("processed", [])
    validation = event.get("validation", {})

    full = next((v for v in processed if v.get("variant") == "full"), None)
    thumb = next((v for v in processed if v.get("variant") == "thumbnail"), None)

    set_status(
        image_id,
        "COMPLETED",
        processedAt=utc_now_iso(),
        sourceKey=event.get("key"),
        originalWidth=validation.get("width"),
        originalHeight=validation.get("height"),
        fullWidth=full.get("width") if full else None,
        fullHeight=full.get("height") if full else None,
        thumbnailWidth=thumb.get("width") if thumb else None,
        thumbnailHeight=thumb.get("height") if thumb else None,
        variants=[
            {"variant": v["variant"], "key": v["key"],
             "width": v["width"], "height": v["height"], "bytes": v["bytes"]}
            for v in processed
        ],
    )

    log.info("Stored metadata for %s (%d variants)", image_id, len(processed))
    return event
