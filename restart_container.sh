#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="rate-announcer"
IMAGE_TAG="ankurbajaj9/home:rate-announcer"
ENV_FILE=".env"

echo "--- stopping container if running ---"
docker stop "$CONTAINER_NAME" 2>/dev/null || true

echo "--- removing old container if exists ---"
docker rm "$CONTAINER_NAME" 2>/dev/null || true

echo "--- pulling latest image: $IMAGE_TAG ---"
docker pull "$IMAGE_TAG"

echo "--- starting container ---"
# Replicate docker-compose minimal settings: host network, env file, restart policy
# Note: on macOS host network mode behaves differently; adjust if needed
docker run -d \
  --name "$CONTAINER_NAME" \
  --network host \
  --env-file "$ENV_FILE" \
  --restart unless-stopped \
  "$IMAGE_TAG"

echo "--- container started ---"
