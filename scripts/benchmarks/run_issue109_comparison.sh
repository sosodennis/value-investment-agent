#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPOSITORY_ROOT"

PROJECT="${ISSUE109_COMPOSE_PROJECT:?set ISSUE109_COMPOSE_PROJECT to the running verification stack}"
TOKEN="${INFERENCE_SERVICE_TOKEN:?set INFERENCE_SERVICE_TOKEN for the service API}"
BASE_IMAGE="${ISSUE109_BASE_BACKEND_IMAGE:-sha256:ba6dac071a004c6a85e9bc66164a2f0ce0b2c30594d50be8686aaeaf6ea0ec72}"
RUNS="${ISSUE109_BENCHMARK_REPETITIONS:-5}"
OUTPUT_DIR="${ISSUE109_BENCHMARK_OUTPUT_DIR:-reports/issue-109/comparison-$(date -u +%Y%m%dT%H%M%SZ)}"

export INFERENCE_SERVICE_TOKEN="$TOKEN"
export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-issue109-validation-only}"
export FRED_API_KEY="${FRED_API_KEY:-issue109-validation-only}"
COMPOSE=(
  docker compose
  -p "$PROJECT"
  -f docker-compose.yml
  -f docker-compose.issue109-offline.yml
)

if ! [[ "$RUNS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'ISSUE109_BENCHMARK_REPETITIONS must be a positive integer.\n' >&2
  exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
  printf 'Refusing to overwrite benchmark output: %s\n' "$OUTPUT_DIR" >&2
  exit 2
fi
if ! docker image inspect "$BASE_IMAGE" >/dev/null 2>&1; then
  printf 'Baseline backend image is not available locally: %s\n' "$BASE_IMAGE" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
"${COMPOSE[@]}" exec -T model-inference-news curl -fsS http://localhost:8001/readyz \
  | jq -e '.ready and .operations["news.sentiment"].ready' >/dev/null
"${COMPOSE[@]}" exec -T model-inference-fls curl -fsS http://localhost:8001/readyz \
  | jq -e '.ready and .operations["sec.fls"].ready' >/dev/null

jq -cn \
  --arg started_at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --arg commit "$(git rev-parse HEAD)" \
  --arg baseline_image "$BASE_IMAGE" \
  --arg baseline_image_id "$(docker image inspect "$BASE_IMAGE" --format '{{.Id}}')" \
  --arg project "$PROJECT" \
  --argjson repetitions "$RUNS" \
  --argjson news_container "$("${COMPOSE[@]}" ps -q model-inference-news | xargs docker inspect --format '{{json .}}' | jq -c '{id:.Id,image:.Image,started_at:.State.StartedAt}')" \
  --argjson fls_container "$("${COMPOSE[@]}" ps -q model-inference-fls | xargs docker inspect --format '{{json .}}' | jq -c '{id:.Id,image:.Image,started_at:.State.StartedAt}')" \
  '{started_at:$started_at,commit:$commit,project:$project,repetitions:$repetitions,baseline:{image:$baseline_image,image_id:$baseline_image_id,cpu_limit:4,memory_limit:"1500m",torch_num_threads:1},news_container:$news_container,fls_container:$fls_container}' \
  > "$OUTPUT_DIR/metadata.json"

run_baseline() {
  local operation="$1"
  local index="$2"
  local output="$3"
  local script
  local common_args

  if [[ "$operation" == "news" ]]; then
    script="finbert_workload.py"
    common_args=(--warmup-requests 1 --sequential 8 --concurrency 1 2 4 8 --requests-per-level 8)
  else
    script="fls_workload.py"
    common_args=(
      --warmup-requests 1
      --sequential 8
      --concurrency 1 2 4 8
      --requests-per-level 8
      --sentences-per-request 16
    )
  fi

  docker run --rm --network none \
    --cpus=4 --memory=1500m \
    --entrypoint /opt/venv/bin/python \
    -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
    -e PYTHONPATH=/app \
    -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 \
    -e HF_HOME=/opt/hf-cache-baked \
    -e HF_HUB_CACHE=/opt/hf-cache-baked/hub \
    -e SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache-baked/hub \
    -e HF_LOCAL_FILES_ONLY=1 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    -e SEC_TEXT_FLS_MODEL=yiyanghkust/finbert-fls \
    "$BASE_IMAGE" "/benchmarks/$script" "${common_args[@]}" \
    > "$output"
  jq -e '.available == true and .load_ms > 0 and (.warmup_inference.errors // 0) == 0 and (.sequential.errors // 0) == 0' "$output" >/dev/null
  if jq -e '(.sequential.errors // 0) > 0 or ([.concurrent[].errors // 0] | any(. > 0))' \
    "$output" >/dev/null; then
    printf 'Baseline workload %s run %s returned invalid output; see %s\n' \
      "$operation" "$index" "$output" >&2
    return 1
  fi
}

run_service() {
  local operation="$1"
  local index="$2"
  local output="$3"
  local service
  local url
  local queue_depth=4

  if [[ "$operation" == "news" ]]; then
    service="model-inference-news"
    url="http://model-inference-news:8001"
  else
    service="model-inference-fls"
    url="http://model-inference-fls:8001"
    queue_depth=1
  fi

  "${COMPOSE[@]}" run --no-deps --rm -T \
    -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
    -e INFERENCE_SERVICE_TOKEN="$TOKEN" \
    --entrypoint /opt/venv/bin/python backend \
    /benchmarks/inference_service_workload.py \
    --base-url "$url" \
    --operation "$([[ "$operation" == "news" ]] && printf 'news.sentiment' || printf 'sec.fls')" \
    --concurrency 1 2 4 8 --requests-per-level 8 --queue-depth "$queue_depth" \
    --allow-error OVERLOADED \
    --sentences-per-request 16 \
    --warmup-requests 1 \
    > "$output"
  jq -e '.capacity_bounds_passed and .output_expectation_passed and .model_revision and (.warmup.errors == 0)' \
    "$output" >/dev/null
}

for operation in news fls; do
  for ((index = 1; index <= RUNS; index++)); do
    printf 'Baseline %s run %s/%s\n' "$operation" "$index" "$RUNS"
    run_baseline "$operation" "$index" "$OUTPUT_DIR/$operation-inprocess-$index.json"
    printf 'Service %s run %s/%s\n' "$operation" "$index" "$RUNS"
    run_service "$operation" "$index" "$OUTPUT_DIR/$operation-http-$index.json"
  done
done

printf 'Comparison completed: %s\n' "$OUTPUT_DIR"
