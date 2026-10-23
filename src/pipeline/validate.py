"""ValidateImage step — reads the uploaded object and checks it is a real,
readable, reasonably sized image. Failures raise ValueError, which the Step
Functions Catch sends to FailJob."""

import io
import logging
import os

import boto3
from PIL import Image, UnidentifiedImageError

from common import set_status, utc_now_iso

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
SOURCE_BUCKET = os.environ["SOURCE_BUCKET"]

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_DIMENSIONS = (10000, 10000)


def lambda_handler(event, context):
    image_id = event["imageId"]
    key = event["key"]

    obj = s3.get_object(Bucket=SOURCE_BUCKET, Key=key)
    data = obj["Body"].read()

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # decode check — catches truncated/corrupt files
    except (UnidentifiedImageError, OSError) as exc:
        set_status(image_id, "FAILED", error=f"invalid image: {exc}")
        raise ValueError(f"Not a valid image: {key}") from exc

    fmt = img.format or "UNKNOWN"
    width, height = img.size
    if fmt not in ALLOWED_FORMATS:
        set_status(image_id, "FAILED", error=f"unsupported format {fmt}")
        raise ValueError(f"Unsupported image format: {fmt}")
    if width > MAX_DIMENSIONS[0] or height > MAX_DIMENSIONS[1]:
        set_status(image_id, "FAILED", error="dimensions out of range")
        raise ValueError(f"Image too large: {width}x{height}")

    # Re-open for a real decode (verify() leaves the file unusable).
    img = Image.open(io.BytesIO(data))
    img.load()

    set_status(image_id, "PROCESSING",
               format=fmt, width=width, height=height,
               validatedAt=utc_now_iso())

    log.info("Validated %s: %s %dx%d (%d bytes)", image_id, fmt, width, height, len(data))
    return {
        "format": fmt,
        "width": width,
        "height": height,
        "sizeBytes": len(data),
        "contentType": obj.get("ContentType", "application/octet-stream"),
    }
