#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPOSITORY_ROOT"

OPERATION="${1:-}"
PROJECT="${ISSUE109_COMPOSE_PROJECT:?set ISSUE109_COMPOSE_PROJECT to the running verification stack}"
TOKEN="${INFERENCE_SERVICE_TOKEN:?set INFERENCE_SERVICE_TOKEN for the service API}"
OUTPUT_DIR="${ISSUE109_SATURATION_OUTPUT_DIR:-reports/issue-109/saturation-$(date -u +%Y%m%dT%H%M%SZ)}"

case "$OPERATION" in
  news)
    SERVICE="model-inference-news"
    WIRE_OPERATION="news.sentiment"
    CONCURRENCY=16
    QUEUE_DEPTH=4
    SENTENCES_PER_REQUEST=1
    ;;
  fls)
    SERVICE="model-inference-fls"
    WIRE_OPERATION="sec.fls"
    CONCURRENCY=12
    QUEUE_DEPTH=1
    SENTENCES_PER_REQUEST=16
    ;;
  *)
    printf 'Usage: %s {news|fls}\n' "$0" >&2
    exit 2
    ;;
esac

COMPOSE=(
  docker compose
  --project-name "$PROJECT"
  -f docker-compose.yml
  -f compose/verification/docker-compose.issue109-offline.yml
)

WORKLOAD_REPORT="$OUTPUT_DIR/$OPERATION-saturation.json"
MEMORY_REPORT="$OUTPUT_DIR/$OPERATION-memory.jsonl"
if [[ -e "$WORKLOAD_REPORT" || -e "$MEMORY_REPORT" ]]; then
  printf 'Refusing to overwrite saturation evidence in %s\n' "$OUTPUT_DIR" >&2
  exit 2
fi
mkdir -p "$OUTPUT_DIR"

container_id="$("${COMPOSE[@]}" ps -q "$SERVICE")"
if [[ -z "$container_id" ]]; then
  printf '%s is not running in Compose project %s\n' "$SERVICE" "$PROJECT" >&2
  exit 2
fi

sample_memory() {
  local sampled_at
  local stats
  sampled_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  stats="$(docker stats --no-stream --format '{{json .}}' "$container_id")"
  jq -cn --arg sampled_at "$sampled_at" --argjson stats "$stats" \
    '{sampled_at:$sampled_at,stats:$stats}' >> "$MEMORY_REPORT"
}

sample_memory
"${COMPOSE[@]}" run --no-deps --rm -T \
  -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
  -e INFERENCE_SERVICE_TOKEN="$TOKEN" \
  --entrypoint /opt/venv/bin/python backend \
  /benchmarks/inference_service_workload.py \
  --base-url "http://$SERVICE:8001" \
  --operation "$WIRE_OPERATION" \
  --concurrency "$CONCURRENCY" \
  --requests-per-level "$CONCURRENCY" \
  --queue-depth "$QUEUE_DEPTH" \
  --sentences-per-request "$SENTENCES_PER_REQUEST" \
  --warmup-requests 1 \
  --require-overload \
  > "$WORKLOAD_REPORT" &
workload_pid=$!

while kill -0 "$workload_pid" 2>/dev/null; do
  sample_memory
  sleep 0.25
done

workload_status=0
wait "$workload_pid" || workload_status=$?
sample_memory
if (( workload_status != 0 )); then
  printf 'Saturation workload failed with exit code %s; see %s\n' \
    "$workload_status" "$WORKLOAD_REPORT" >&2
  exit "$workload_status"
fi

jq -e \
  '.capacity_bounds_passed and .overload_expectation_passed and .output_expectation_passed and .unexpected_errors == 0 and ([.levels[].deadline_exceeded] | add) == 0' \
  "$WORKLOAD_REPORT" >/dev/null

printf 'Saturation evidence saved: %s and %s\n' "$WORKLOAD_REPORT" "$MEMORY_REPORT"
