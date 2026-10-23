"""Resize step — runs twice, once per branch of the Parallel state:
  * lambda_handler_thumbnail: 256x256 square crop  -> processed/<id>/thumbnail.jpg
  * lambda_handler_fullres:   max 1920px long side -> processed/<id>/full.jpg
"""

import io
import logging
import os

import boto3
from PIL import Image, ImageOps

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
SOURCE_BUCKET = os.environ["SOURCE_BUCKET"]
DESTINATION_BUCKET = os.environ["DESTINATION_BUCKET"]

THUMBNAIL_SIZE = (256, 256)
FULLRES_MAX = 1920
JPEG_QUALITY = 85


def lambda_handler_thumbnail(event, context):
    return _resize(event, variant="thumbnail")


def lambda_handler_fullres(event, context):
    return _resize(event, variant="full")


def _resize(event, variant):
    image_id = event["imageId"]
    key = event["key"]

    data = s3.get_object(Bucket=SOURCE_BUCKET, Key=key)["Body"].read()
    img = Image.open(io.BytesIO(data))

    # Flatten transparency onto white so JPEG export keeps colours.
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background.convert("RGB")
    elif img.mode != "RGB":
        img = img.convert("RGB")

    if variant == "thumbnail":
        out = ImageOps.fit(img, THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
    else:
        img.thumbnail((FULLRES_MAX, FULLRES_MAX), Image.Resampling.LANCZOS)
        out = img

    buffer = io.BytesIO()
    out.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    buffer.seek(0)

    dest_key = f"processed/{image_id}/{variant}.jpg"
    s3.put_object(
        Bucket=DESTINATION_BUCKET,
        Key=dest_key,
        Body=buffer.getvalue(),
        ContentType="image/jpeg",
        CacheControl="public, max-age=31536000, immutable",
    )

    log.info("Resized %s -> %s (%dx%d)", key, dest_key, out.width, out.height)
    return {
        "variant": variant,
        "bucket": DESTINATION_BUCKET,
        "key": dest_key,
        "width": out.width,
        "height": out.height,
        "bytes": buffer.getbuffer().nbytes,
    }
