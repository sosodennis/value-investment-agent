#!/usr/bin/env bash
set -euo pipefail

# Remove only this project's dangling images older than the retention window.
# Tagged/referenced images, volumes and build cache are preserved.
PROJECT="${DOCKER_CLEANUP_PROJECT:-}"
if ! [[ "$PROJECT" =~ ^value-investment-agent-[a-z0-9][a-z0-9_-]*$ ]]; then
  echo "Set DOCKER_CLEANUP_PROJECT to one exact value-investment-agent-* project" >&2
  exit 2
fi

RETENTION_HOURS="${DOCKER_DANGLING_IMAGE_RETENTION_HOURS:-168}"
if ! [[ "${RETENTION_HOURS}" =~ ^[0-9]+$ ]]; then
  echo "DOCKER_DANGLING_IMAGE_RETENTION_HOURS must be a non-negative integer" >&2
  exit 2
fi

docker image prune --force \
  --filter dangling=true \
  --filter "label=com.docker.compose.project=$PROJECT" \
  --filter "until=${RETENTION_HOURS}h"
