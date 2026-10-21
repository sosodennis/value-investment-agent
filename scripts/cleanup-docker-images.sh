#!/usr/bin/env bash
set -euo pipefail

# Remove only dangling images older than the retention window. This does not
# remove tagged images, images used by containers, volumes, or build cache.
RETENTION_HOURS="${DOCKER_DANGLING_IMAGE_RETENTION_HOURS:-168}"
if ! [[ "${RETENTION_HOURS}" =~ ^[0-9]+$ ]]; then
  echo "DOCKER_DANGLING_IMAGE_RETENTION_HOURS must be a non-negative integer" >&2
  exit 2
fi

docker image prune --force \
  --filter dangling=true \
  --filter "until=${RETENTION_HOURS}h"
