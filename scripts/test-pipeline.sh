#!/usr/bin/env bash
# End-to-end smoke test for the image pipeline.
#
# Usage:  ./scripts/test-pipeline.sh [path-to-image.jpg]
#
# Reads the deployed stack outputs, gets a pre-signed URL from the API,
# uploads an image, then waits for DynamoDB to report COMPLETED and lists
# the generated files.
set -euo pipefail

STACK_NAME="${STACK_NAME:-image-pipeline}"
REGION="${AWS_REGION:-us-east-1}"
IMAGE="${1:-}"
WAIT_SECONDS=90

command -v aws >/dev/null || { echo "aws CLI is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required" >&2; exit 1; }

echo "==> Reading stack outputs ($STACK_NAME in $REGION)..."
mapfile -t OUT < <(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" --region "$REGION" \
  --query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output text)

get_output() {
  for row in "${OUT[@]}"; do
    key="${row%%$'\t'*}"; value="${row#*$'\t'}"
    [ "$key" = "$1" ] && { echo "$value"; return; }
  done
}

API_URL=$(get_output PresignApiUrl)
TABLE=$(get_output DynamoDBTableName)
DEST_BUCKET=$(get_output DestinationBucketName)
CF_DOMAIN=$(get_output CloudFrontDomain)

[ -n "$API_URL" ] || { echo "Could not read stack outputs — is the stack deployed?" >&2; exit 1; }

# Create a sample image locally if none was provided.
if [ -z "$IMAGE" ]; then
  IMAGE="$(mktemp --suffix=.jpg)"
  python3 - "$IMAGE" <<'PY' 2>/dev/null || true
import sys
try:
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1600, 1000), (30, 64, 120))
    d = ImageDraw.Draw(img)
    d.ellipse((500, 250, 1100, 750), fill=(240, 200, 60))
    img.save(sys.argv[1], "JPEG", quality=90)
except ImportError:
    sys.exit(1)  # fall through to the bundled PNG below
PY
  if [ ! -s "$IMAGE" ]; then
    IMAGE="$(mktemp --suffix=.png)"
    # 64x64 red PNG, base64-encoded
    base64 -d > "$IMAGE" <<'B64'
iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAYAAACqaXHeAAAAKklEQVR4nO3NMQEA
IAzAsIF/z0MGBuSyyVT9ZgAAAAAAAAAAAAAAAPhYbH2sAAAA//8DAB0EGXkO0xqo
AAAAAElFTkSuQmCC
B64
  fi
  echo "==> Using generated sample image: $IMAGE"
fi

echo "==> Requesting pre-signed upload URL..."
RESPONSE=$(curl -sS -X POST "$API_URL" \
  -H 'Content-Type: application/json' \
  -d "{\"filename\": \"$(basename "$IMAGE")\", \"contentType\": \"image/jpeg\"}")

IMAGE_ID=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["imageId"])')
UPLOAD_URL=$(echo "$RESPONSE" | python3 -c 'import sys, json; print(json.load(sys.stdin)["uploadUrl"])')
echo "    imageId = $IMAGE_ID"

echo "==> Uploading image..."
curl -sS -o /dev/null -w '    HTTP %{http_code}\n' -X PUT "$UPLOAD_URL" \
  -H 'Content-Type: image/jpeg' --data-binary "@$IMAGE"

echo "==> Waiting for DynamoDB status=COMPLETED (up to ${WAIT_SECONDS}s)..."
for _ in $(seq 1 "$WAIT_SECONDS"); do
  STATUS=$(aws dynamodb get-item --table-name "$TABLE" --region "$REGION" \
    --key "{\"imageId\": {\"S\": \"$IMAGE_ID\"}}" \
    --query 'Item.status.S' --output text 2>/dev/null || echo "MISSING")
  if [ "$STATUS" = "COMPLETED" ] || [ "$STATUS" = "FAILED" ]; then break; fi
  sleep 2
done
echo "    status = $STATUS"

if [ "$STATUS" = "COMPLETED" ]; then
  echo "==> Generated files (via CloudFront: https://$CF_DOMAIN):"
  aws s3 ls "s3://$DEST_BUCKET/processed/$IMAGE_ID/" --recursive
  echo "==> Thumbnail URL: https://$CF_DOMAIN/processed/$IMAGE_ID/thumbnail.jpg"
  echo "==> Full-res URL:  https://$CF_DOMAIN/processed/$IMAGE_ID/full.jpg"
  echo "==> Metadata:"
  aws dynamodb get-item --table-name "$TABLE" --region "$REGION" \
    --key "{\"imageId\": {\"S\": \"$IMAGE_ID\"}}" --output json | python3 -m json.tool
else
  echo "!! Pipeline did not complete in time. Check the DLQ and Step Functions console." >&2
  aws sqs receive-message \
    --queue-url "$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
      --region "$REGION" --query 'Stacks[0].Outputs[?OutputKey==`DeadLetterQueueUrl`].OutputValue' \
      --output text)" || true
  exit 1
fi
