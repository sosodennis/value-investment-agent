#!/usr/bin/env bash
set -euo pipefail

REPOSITORY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPOSITORY_ROOT"

PROJECT="${ISSUE109_COMPOSE_PROJECT:-value-investment-agent-issue109-$(date -u +%H%M%S)}"
BASE_BACKEND_IMAGE="${ISSUE109_BASE_BACKEND_IMAGE:-via-llm-stage-backend:latest}"
UPDATED_BACKEND_IMAGE="${ISSUE109_UPDATED_BACKEND_IMAGE:-${PROJECT}-backend:issue109}"
REPORT="${ISSUE109_DEPLOYMENT_REPORT:-reports/issue-109/deployment-$(date -u +%Y%m%dT%H%M%SZ).jsonl}"
MAX_WAIT_SECONDS="${ISSUE109_HEALTH_TIMEOUT_SECONDS:-300}"

export INFERENCE_SERVICE_TOKEN="${INFERENCE_SERVICE_TOKEN:-issue109-validation-token-$$}"
export INFERENCE_ALLOW_INSECURE=0
export LLM_PROVIDER_ENCRYPTION_KEY="${LLM_PROVIDER_ENCRYPTION_KEY:-JRNZ1-TpUwO-4trpfntsDM92mUvk3Oluu1MCsvZHpRU=}"
export FRED_API_KEY="${FRED_API_KEY:-issue109-validation-only}"
export BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-18109}"
export POSTGRES_HOST_PORT="${POSTGRES_HOST_PORT:-15432}"
export REDIS_HOST_PORT="${REDIS_HOST_PORT:-16379}"
export ISSUE109_BACKEND_IMAGE="$UPDATED_BACKEND_IMAGE"

COMPOSE=(
  docker compose
  --project-name "$PROJECT"
  -f docker-compose.yml
  -f compose/verification/docker-compose.issue109-offline.yml
)

if ! command -v jq >/dev/null 2>&1; then
  printf 'jq is required to record deployment evidence.\n' >&2
  exit 2
fi

if ! docker image inspect "$BASE_BACKEND_IMAGE" >/dev/null 2>&1; then
  printf 'Base backend image is not available locally: %s\n' "$BASE_BACKEND_IMAGE" >&2
  exit 2
fi

if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] || \
   [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]] || \
   [[ -n "$(docker volume ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  printf 'Compose project already has resources: %s\n' "$PROJECT" >&2
  printf 'Choose a new ISSUE109_COMPOSE_PROJECT to preserve the existing evidence.\n' >&2
  exit 2
fi

mkdir -p "$(dirname "$REPORT")"
if [[ -e "$REPORT" ]]; then
  printf 'Refusing to overwrite deployment report: %s\n' "$REPORT" >&2
  exit 2
fi
: > "$REPORT"

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" build model-inference-news model-inference-fls
"${COMPOSE[@]}" build backend

wait_healthy() {
  local service="$1"
  local deadline=$((SECONDS + MAX_WAIT_SECONDS))
  local container_id=""
  local health="missing"

  while (( SECONDS < deadline )); do
    container_id="$("${COMPOSE[@]}" ps -q "$service")"
    if [[ -n "$container_id" ]]; then
      health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
      if [[ "$health" == "healthy" ]]; then
        return 0
      fi
    fi
    sleep 2
  done

  printf '%s did not become healthy; last state=%s\n' "$service" "$health" >&2
  "${COMPOSE[@]}" logs --tail=100 "$service" >&2 || true
  return 1
}

assert_offline_artifacts() {
  local service="$1"
  local container_id
  local internal_network

  container_id="$("${COMPOSE[@]}" ps -q "$service")"
  internal_network="$(docker network inspect "${PROJECT}_default" --format '{{.Internal}}')"
  if [[ "$internal_network" != "true" ]]; then
    printf 'Runtime network is not internal: %s\n' "$PROJECT" >&2
    return 1
  fi
  for variable in HF_HUB_OFFLINE TRANSFORMERS_OFFLINE HF_LOCAL_FILES_ONLY; do
    if ! docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$container_id" \
      | rg -q "^${variable}=1$"; then
      printf '%s is not enabled in %s\n' "$variable" "$service" >&2
      return 1
    fi
  done
}

record_inference_snapshot() {
  local phase="$1"
  local service="$2"
  local operation="$3"
  local container_id
  local started_at
  local image_id
  local readiness
  local details
  local revision

  container_id="$("${COMPOSE[@]}" ps -q "$service")"
  started_at="$(docker inspect --format '{{.State.StartedAt}}' "$container_id")"
  image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
  readiness="$("${COMPOSE[@]}" exec -T "$service" curl -fsS http://localhost:8001/readyz)"
  details="$("${COMPOSE[@]}" exec -T "$service" curl -fsS http://localhost:8001/readyz/details)"
  if ! jq -e '.status == "ready" and .contract_version == "internal.v1"' \
    <<<"$readiness" >/dev/null; then
    printf '%s was not ready and accepting requests\n' "$service" >&2
    return 1
  fi
  if ! jq -e --arg operation "$operation" \
    '.operations[$operation].ready == true and .operations[$operation].accepting == true' \
    <<<"$details" >/dev/null; then
    printf '%s was not ready and accepting requests\n' "$service" >&2
    return 1
  fi
  revision="$(jq -er --arg operation "$operation" '.operations[$operation].model_revision' <<<"$details")"
  jq -cn \
    --arg phase "$phase" \
    --arg commit "$(git rev-parse HEAD)" \
    --arg service "$service" \
    --arg container_id "$container_id" \
    --arg started_at "$started_at" \
    --arg image_id "$image_id" \
    --arg model_revision "$revision" \
    --argjson readiness "$readiness" \
    --argjson details "$details" \
    '{phase:$phase,commit:$commit,service:$service,container_id:$container_id,started_at:$started_at,image_id:$image_id,model_revision:$model_revision,readiness:$readiness,details:$details}' \
    >> "$REPORT"
  printf '%s\t%s\t%s\t%s\t%s\n' "$service" "$container_id" "$started_at" "$image_id" "$revision"
}

record_backend_snapshot() {
  local phase="$1"
  local container_id
  local started_at
  local image_id
  local health

  container_id="$("${COMPOSE[@]}" ps -q backend)"
  started_at="$(docker inspect --format '{{.State.StartedAt}}' "$container_id")"
  image_id="$(docker inspect --format '{{.Image}}' "$container_id")"
  health="$(docker inspect --format '{{.State.Health.Status}}' "$container_id")"
  jq -cn \
    --arg phase "$phase" \
    --arg commit "$(git rev-parse HEAD)" \
    --arg service backend \
    --arg container_id "$container_id" \
    --arg started_at "$started_at" \
    --arg image_id "$image_id" \
    --arg health "$health" \
    '{phase:$phase,commit:$commit,service:$service,container_id:$container_id,started_at:$started_at,image_id:$image_id,health:$health}' \
    >> "$REPORT"
  printf '%s\t%s\t%s\t%s\n' "$container_id" "$started_at" "$image_id" "$health"
}

inference_start_epoch="$SECONDS"
"${COMPOSE[@]}" up -d --no-build --pull never model-inference-news model-inference-fls
wait_healthy model-inference-news
news_startup_seconds=$((SECONDS - inference_start_epoch))
wait_healthy model-inference-fls
fls_startup_seconds=$((SECONDS - inference_start_epoch))
assert_offline_artifacts model-inference-news
assert_offline_artifacts model-inference-fls
jq -cn \
  --arg project "$PROJECT" \
  --arg commit "$(git rev-parse HEAD)" \
  --arg architecture "$(docker info --format '{{.Architecture}}')" \
  --argjson memory_bytes "$(docker info --format '{{.MemTotal}}')" \
  --argjson news_startup_seconds "$news_startup_seconds" \
  --argjson fls_startup_seconds "$fls_startup_seconds" \
  '{phase:"offline-startup",project:$project,commit:$commit,architecture:$architecture,docker_memory_bytes:$memory_bytes,news_ready_seconds:$news_startup_seconds,fls_ready_seconds:$fls_startup_seconds}' \
  >> "$REPORT"

ISSUE109_BACKEND_IMAGE="$BASE_BACKEND_IMAGE" \
  "${COMPOSE[@]}" up -d --no-build --pull never backend
wait_healthy backend

before_news="$(record_inference_snapshot before-backend-update model-inference-news news.sentiment)"
before_fls="$(record_inference_snapshot before-backend-update model-inference-fls sec.fls)"
before_backend="$(record_backend_snapshot before-backend-update)"

ISSUE109_BACKEND_IMAGE="$UPDATED_BACKEND_IMAGE" \
  "${COMPOSE[@]}" up -d --no-build --pull never backend
wait_healthy backend

after_news="$(record_inference_snapshot after-backend-update model-inference-news news.sentiment)"
after_fls="$(record_inference_snapshot after-backend-update model-inference-fls sec.fls)"
after_backend="$(record_backend_snapshot after-backend-update)"

backend_probe="$("${COMPOSE[@]}" exec -T backend python -c '
import asyncio
import json
import time

from src.model_inference.entrypoint import close_model_inference, get_model_inference
from src.model_inference.entrypoint import InferenceFailure


async def main():
    inference = get_model_inference()

    async def sample(operation, call):
        started = time.perf_counter()
        try:
            result = await call() if operation == "news" else call()
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            if operation == "news":
                return {
                    "ok": True,
                    "elapsed_ms": elapsed_ms,
                    "label": result.label,
                    "model_revision": result.model_revision,
                }
            return {
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "prediction_count": len(result.predictions),
                "model_revision": result.model_revision,
            }
        except InferenceFailure as error:
            return {
                "ok": False,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "error_code": error.code.value,
            }

    try:
        warmup_probe = {
            "news": await sample(
                "news",
                lambda: inference.news_sentiment(
                    "Revenue increased and operating margins improved."
                ),
            ),
            "fls": await sample(
                "fls",
                lambda: inference.fls_predictions(
                    [
                        "Management expects revenue growth to continue next year.",
                        "The board approved a dividend during the reporting period.",
                    ]
                ),
            ),
        }
        news = [
            await sample(
                "news",
                lambda: inference.news_sentiment(
                    "Revenue increased and operating margins improved."
                ),
            )
            for _ in range(5)
        ]
        fls = [
            await sample(
                "fls",
                lambda: inference.fls_predictions(
                    [
                        "Management expects revenue growth to continue next year.",
                        "The board approved a dividend during the reporting period.",
                    ]
                ),
            )
            for _ in range(5)
        ]
        print(
            json.dumps(
                {"warmup_probe": warmup_probe, "news": news, "fls": fls},
                sort_keys=True,
            )
        )
    finally:
        await close_model_inference()


asyncio.run(main())
')"
if ! jq -e \
  '(.news | length == 5 and all(.[]; .ok and (.model_revision | strings | length > 0))) and (.fls | length == 5 and all(.[]; .ok and .prediction_count == 2 and (.model_revision | strings | length > 0)))' \
  <<<"$backend_probe" >/dev/null; then
  printf 'Backend caller probe did not produce valid News and FLS results\n' >&2
  exit 1
fi
jq -cn \
  --arg phase backend-inference-probe \
  --arg commit "$(git rev-parse HEAD)" \
  --argjson result "$backend_probe" \
  '{phase:$phase,commit:$commit,result:$result}' \
  >> "$REPORT"
if jq -e '[.news[], .fls[]] | any(.[]; .ok == false)' <<<"$backend_probe" >/dev/null; then
  printf 'Backend caller probe observed an inference failure; inspect the deployment report.\n' >&2
  exit 1
fi

if [[ "$before_news" != "$after_news" ]]; then
  printf 'News inference identity or loaded model changed during backend update\n' >&2
  exit 1
fi
if [[ "$before_fls" != "$after_fls" ]]; then
  printf 'FLS inference identity or loaded model changed during backend update\n' >&2
  exit 1
fi

before_backend_id="$(cut -f1 <<<"$before_backend")"
after_backend_id="$(cut -f1 <<<"$after_backend")"
before_backend_image="$(cut -f3 <<<"$before_backend")"
after_backend_image="$(cut -f3 <<<"$after_backend")"
if [[ "$before_backend_id" == "$after_backend_id" ]]; then
  printf 'Backend container was not replaced during the update\n' >&2
  exit 1
fi
if [[ "$before_backend_image" == "$after_backend_image" ]]; then
  printf 'Backend image did not change during the update\n' >&2
  exit 1
fi

printf 'PASS: inference service identities and model revisions survived backend-only replacement.\n'
printf 'Report: %s\n' "$REPORT"
