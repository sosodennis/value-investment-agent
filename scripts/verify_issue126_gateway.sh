#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="${ISSUE126_GATEWAY_COMPOSE_PROJECT:-value-investment-agent-issue126-gateway-$(date -u +%Y%m%d%H%M%S)}"
HEALTH_TIMEOUT_SECONDS="${ISSUE126_HEALTH_TIMEOUT_SECONDS:-300}"

export LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY:-issue126-disposable-gateway-key}"
export LLM_PROVIDER_SERVICE_TOKEN="${LLM_PROVIDER_SERVICE_TOKEN:-issue126-disposable-provider-token}"
export SEARCH_PROVIDER_ENCRYPTION_KEY="${SEARCH_PROVIDER_ENCRYPTION_KEY:-ZWRpc2FibGUtaXNzdWUxMjYtZW5jcnlwdGlvbi1rZXk=}"
export FRED_API_KEY="${FRED_API_KEY:-issue126-disposable-fred-token}"
export LLM_GATEWAY_MEMORY_LIMIT="${LLM_GATEWAY_MEMORY_LIMIT:-2g}"

COMPOSE=(
  docker compose
  --profile llm-gateway
  --project-name "$PROJECT"
  -f docker-compose.yml
  -f docker-compose.production.yml
  -f compose/verification/docker-compose.issue126-verification.yml
)

cleanup() {
  "${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ -n "$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT")" ]] || \
  [[ -n "$(docker network ls -q --filter "label=com.docker.compose.project=$PROJECT")" ]]; then
  echo "Compose project already has resources: $PROJECT" >&2
  exit 2
fi

"${COMPOSE[@]}" config --quiet
"${COMPOSE[@]}" up -d --pull never postgres redis llm-gateway-db-init llm-gateway

gateway_id=""
deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS))
while (( SECONDS < deadline )); do
  gateway_id="$(${COMPOSE[@]} ps -q llm-gateway)"
  if [[ -n "$gateway_id" ]] && [[ "$(docker inspect --format '{{.State.Health.Status}}' "$gateway_id")" == "healthy" ]]; then
    break
  fi
  sleep 2
done
if [[ -z "$gateway_id" ]] || [[ "$(docker inspect --format '{{.State.Health.Status}}' "$gateway_id")" != "healthy" ]]; then
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail=120 llm-gateway >&2 || true
  exit 1
fi

"${COMPOSE[@]}" run --rm --no-deps -T \
  -v "$ROOT/scripts/issue126_gateway_probe.py:/tmp/issue126_gateway_probe.py:ro" \
  -e LITELLM_MASTER_KEY="$LITELLM_MASTER_KEY" \
  --entrypoint python llm-gateway /tmp/issue126_gateway_probe.py
