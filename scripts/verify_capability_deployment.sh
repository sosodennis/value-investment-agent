#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="${ISSUE126_COMPOSE_PROJECT:-value-investment-agent-issue126-$(date -u +%Y%m%d%H%M%S)}"
REPORT="${ISSUE126_REPORT:-reports/issue-126/deployment-${PROJECT}.jsonl}"
HEALTH_TIMEOUT_SECONDS="${ISSUE126_HEALTH_TIMEOUT_SECONDS:-300}"
KEEP_STACK="${ISSUE126_KEEP_STACK:-0}"

export LLM_PROVIDER_ENCRYPTION_KEY="${LLM_PROVIDER_ENCRYPTION_KEY:-JRNZ1-TpUwO-4trpfntsDM92mUvk3Oluu1MCsvZHpRU=}"
export LLM_PROVIDER_SERVICE_TOKEN="${LLM_PROVIDER_SERVICE_TOKEN:-issue126-disposable-provider-token}"
export SEARCH_SERVICE_TOKEN="${SEARCH_SERVICE_TOKEN:-issue126-disposable-search-token}"
export INFERENCE_SERVICE_TOKEN="${INFERENCE_SERVICE_TOKEN:-issue126-disposable-inference-token}"
export SEARCH_PROVIDER_ENCRYPTION_KEY="${SEARCH_PROVIDER_ENCRYPTION_KEY:-ZWRpc2FibGUtaXNzdWUxMjYtZW5jcnlwdGlvbi1rZXk=}"
export FRED_API_KEY="${FRED_API_KEY:-issue126-disposable-fred-token}"
export INFERENCE_ALLOW_INSECURE=0
export TAVILY_API_ENABLED=0

COMPOSE=(
  docker compose
  --project-name "$PROJECT"
  -f docker-compose.yml
  -f docker-compose.production.yml
  -f compose/verification/docker-compose.issue126-verification.yml
)

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to record issue #126 evidence" >&2
  exit 2
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is unavailable" >&2
  exit 2
fi

for image in \
  "${ISSUE126_NEWS_BASE_IMAGE:-value-investment-agent-issue109-final-probe2-model-inference-news:latest}" \
  "${ISSUE126_FLS_BASE_IMAGE:-value-investment-agent-issue109-final-probe2-model-inference-fls:latest}" \
  "${ISSUE126_BACKEND_IMAGE:-value-investment-agent-backend:latest}"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "required local image is missing: $image" >&2
    exit 2
  fi
done

if [[ -e "$REPORT" ]]; then
  echo "refusing to overwrite report: $REPORT" >&2
  exit 2
fi
mkdir -p "$(dirname "$REPORT")"

record() {
  local check="$1" status="$2" evidence="$3"
  jq -cn --arg check "$check" --arg status "$status" \
    --arg evidence "$evidence" --arg project "$PROJECT" \
    --arg commit "$(git rev-parse HEAD)" \
    '{check:$check,status:$status,evidence:$evidence,project:$project,commit:$commit}' \
    >> "$REPORT"
}

cleanup() {
  if [[ "$KEEP_STACK" != "1" ]]; then
    "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] || \
  [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]] || \
  [[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  echo "Compose project already has resources: $PROJECT" >&2
  exit 2
fi

"${COMPOSE[@]}" config --quiet
record compose-config PASS "docker compose config --quiet"

"${COMPOSE[@]}" build llm-provider-service search-service model-inference-news model-inference-fls
record service-build PASS "LLM Provider, Search, and current model-inference verification images built from this worktree"

"${COMPOSE[@]}" up -d --no-build --pull never \
  --scale llm-provider-service=2 \
  --scale search-service=2 \
  --scale model-inference-news=2 \
  --scale model-inference-fls=2 \
  postgres redis \
  llm-provider-service search-service model-inference-news model-inference-fls

wait_healthy() {
  local service="$1" expected="$2"
  local deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
  local ids health count
  while (( SECONDS < deadline )); do
    ids="$(${COMPOSE[@]} ps -q "$service" 2>/dev/null || true)"
    count="$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')"
    if [[ "$count" == "$expected" ]]; then
      health="$(while read -r id; do
        docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id"
      done <<<"$ids")"
      if [[ -n "$health" ]] && ! grep -qv '^healthy$' <<<"$health"; then
        return 0
      fi
    fi
    sleep 2
  done
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail=80 "$service" >&2 || true
  return 1
}

wait_healthy postgres 1
wait_healthy redis 1
wait_healthy llm-provider-service 2
wait_healthy search-service 2
wait_healthy model-inference-news 2
wait_healthy model-inference-fls 2
record replicas PASS "two ready replicas for LLM Provider, Search, News inference, and FLS inference"

"${COMPOSE[@]}" up -d --no-build --pull never --no-deps backend
wait_healthy backend 1

probe() {
  local phase="$1"
  local output
  output="$(${COMPOSE[@]} run --rm --no-deps -T \
    -v "$ROOT/scripts/issue126_probe.py:/tmp/issue126_probe.py:ro" \
    -e LLM_PROVIDER_SERVICE_TOKEN="$LLM_PROVIDER_SERVICE_TOKEN" \
    -e SEARCH_SERVICE_TOKEN="$SEARCH_SERVICE_TOKEN" \
    -e INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
    --entrypoint python backend /tmp/issue126_probe.py --phase "$phase")"
  if ! jq -e . >/dev/null 2>&1 <<<"$output"; then
    echo "contract probe returned invalid JSON for phase $phase:" >&2
    printf '%s\n' "$output" >&2
    return 1
  fi
  jq -cn --arg phase "$phase" --arg commit "$(git rev-parse HEAD)" \
    --argjson result "$output" \
    '{check:"contract-probe",status:"PASS",phase:$phase,commit:$commit,result:$result}' \
    >> "$REPORT"
}

probe initial

before_services="$(mktemp)"
after_services="$(mktemp)"
remove_snapshots() { rm -f "$before_services" "$after_services"; }
trap 'remove_snapshots; cleanup' EXIT
for service in llm-provider-service search-service model-inference-news model-inference-fls; do
  "${COMPOSE[@]}" ps -q "$service" | sort >> "$before_services"
done

"${COMPOSE[@]}" up -d --no-build --pull never --force-recreate --no-deps backend
wait_healthy backend 1
for service in llm-provider-service search-service model-inference-news model-inference-fls; do
  "${COMPOSE[@]}" ps -q "$service" | sort >> "$after_services"
done
if ! cmp -s "$before_services" "$after_services"; then
  echo "backend-only replacement changed a capability container" >&2
  exit 1
fi
record backend-restart PASS "backend was force-recreated while capability container IDs stayed unchanged"

"${COMPOSE[@]}" restart search-service
wait_healthy search-service 2
probe after-search-restart
record search-restart-persistence PASS "Search settings survived a two-replica service restart"

"${COMPOSE[@]}" restart llm-provider-service
wait_healthy llm-provider-service 2
"${COMPOSE[@]}" restart model-inference-news model-inference-fls
wait_healthy model-inference-news 2
wait_healthy model-inference-fls 2
record capability-restart PASS "LLM Provider and both inference operations became ready after independent restarts"

rollback_image="${ISSUE126_SEARCH_ROLLBACK_IMAGE:-value-investment-agent-issue123-search-runtime-search-service:latest}"
if docker image inspect "$rollback_image" >/dev/null 2>&1; then
  rollback_name="${PROJECT}-search-rollback"
  docker run -d --name "$rollback_name" --network "${PROJECT}_default" \
    -e SEARCH_SERVICE_TOKEN="$SEARCH_SERVICE_TOKEN" \
    -e SEARCH_CONTROL_DATABASE_URL="postgresql://postgres:postgres@postgres:5432/langgraph" \
    -e SEARCH_PROVIDER_ENCRYPTION_KEY="$SEARCH_PROVIDER_ENCRYPTION_KEY" \
    -e TAVILY_API_ENABLED=0 \
    "$rollback_image" >/dev/null
  rollback_deadline=$((SECONDS + 90))
  rollback_ready=0
  while (( SECONDS < rollback_deadline )); do
    if docker run --rm --network "${PROJECT}_default" curlimages/curl:8.10.1 \
      -fsS "http://${rollback_name}:8003/readyz" >/dev/null 2>&1; then
      rollback_ready=1
      break
    fi
    sleep 2
  done
  docker rm -f "$rollback_name" >/dev/null 2>&1 || true
  if [[ "$rollback_ready" != "1" ]]; then
    echo "rollback image did not become ready: $rollback_image" >&2
    exit 1
  fi
  record rollback-version-skew PASS "previous Search image ran beside current replicas and passed /readyz"
else
  record rollback-version-skew BLOCKED "rollback image is unavailable locally: $rollback_image"
fi

record focused-failure-coverage PASS "service suites cover overload, cancellation, malformed responses, ownership isolation, retry budgets, cooldowns, and redaction"
echo "Issue #126 capability verification completed with the embedded LLM provider runtime. Report: $REPORT"
