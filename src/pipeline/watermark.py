"""Watermark step — burns WATERMARK_TEXT into every variant produced by the
Parallel state. Input `variants` is the Parallel state's array-of-arrays
output; this handler flattens it, watermarks each object in place and returns
a flat list under `processed`.
"""

import io
import logging
import os

import boto3
from PIL import Image, ImageDraw, ImageFont

from common import utc_now_iso

log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")
DESTINATION_BUCKET = os.environ["DESTINATION_BUCKET"]
WATERMARK_TEXT = os.environ.get("WATERMARK_TEXT", "© ImagePipeline")
OPACITY = 170  # 0-255


def lambda_handler(event, context):
    # Parallel ResultPath produces [[branchA...], [branchB...]] — flatten it.
    variants = [v for branch in event.get("variants", []) for v in (branch or [])]

    processed = []
    for variant in variants:
        key = variant["key"]
        data = s3.get_object(Bucket=DESTINATION_BUCKET, Key=key)["Body"].read()
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        img = _draw_watermark(img)
        out = img.convert("RGB")

        buffer = io.BytesIO()
        out.save(buffer, format="JPEG", quality=85, optimize=True)
        s3.put_object(
            Bucket=DESTINATION_BUCKET,
            Key=key,
            Body=buffer.getvalue(),
            ContentType="image/jpeg",
            CacheControl="public, max-age=31536000, immutable",
        )
        processed.append({
            **variant,
            "width": out.width,
            "height": out.height,
            "bytes": buffer.getbuffer().nbytes,
            "watermarkedAt": utc_now_iso(),
        })
        log.info("Watermarked %s", key)

    return {"imageId": event["imageId"], "processed": processed}


def _draw_watermark(img: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(18, img.width // 22)
    try:
        # Pillow >= 10.1 ships a scalable default font.
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()

    left, top, right, bottom = draw.textbbox((0, 0), WATERMARK_TEXT, font=font)
    text_w, text_h = right - left, bottom - top
    margin = max(12, img.width // 40)
    position = (img.width - text_w - margin, img.height - text_h - margin)

    # Soft shadow, then the text itself.
    draw.text((position[0] + 2, position[1] + 2), WATERMARK_TEXT,
              font=font, fill=(0, 0, 0, OPACITY // 2))
    draw.text(position, WATERMARK_TEXT, font=font, fill=(255, 255, 255, OPACITY))
    return Image.alpha_composite(img, overlay)
