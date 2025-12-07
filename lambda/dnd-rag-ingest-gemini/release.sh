#!/usr/bin/env bash
set -euo pipefail

IMAGE=dnd-rag-ingest-gemini
CONTAINER=${IMAGE}-instance
FUNCTION_NAME=dnd-rag-ingest-gemini

TIMESTAMP=$(date +%s)
ZIP=dnd-rag-ingest-gemini-lambda-release-${TIMESTAMP}.zip

# Clean old artifacts
rm -rf dimg

# Build image
docker build -t "${IMAGE}" .

# Ensure container is gone
docker rm -f "${CONTAINER}" 2>/dev/null || true

# Run container and extract deps
docker run -d --name "${CONTAINER}" "${IMAGE}"
docker cp "${CONTAINER}:/opt/python" dimg

# Add handler
cp lambda_function.py dimg/

# Zip lambda package
(
  cd dimg
  zip -vr "../${ZIP}" .
)

# Update Lambda
aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --zip-file "fileb://${ZIP}" \
  --no-cli-pager
