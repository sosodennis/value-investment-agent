#!/usr/bin/env bash
set -euo pipefail

# Re-runnable staging probe for the canonical /api/v1 contract. The script
# deliberately keeps provider responses in temporary files and records only
# masked metadata in the report.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8000}"
BACKEND_ORIGIN="${STAGING_BASE_URL:-http://127.0.0.1:${BACKEND_HOST_PORT}}"
BACKEND_ORIGIN="${BACKEND_ORIGIN%/}"
SECRET_FILE="${STAGING_SECRET_FILE:-$ROOT/.env}"
REPORT="${STAGING_SMOKE_REPORT:-$ROOT/.audit/refactor-staging-smoke.jsonl}"
TIMEOUT_SECONDS="${STAGING_SMOKE_TIMEOUT_SECONDS:-90}"
RETRY_ATTEMPTS="${STAGING_SMOKE_RETRY_ATTEMPTS:-3}"
THREAD_ID="refactor-smoke-$(date -u +%Y%m%d%H%M%S)-$$"

for command in curl jq awk sed mktemp date; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "required command is missing: $command" >&2
    exit 2
  }
done

read_secret() {
  local name="$1" value=""
  if [[ -n "${!name-}" ]]; then
    printf '%s' "${!name}"
    return 0
  fi
  if [[ -f "$SECRET_FILE" ]]; then
    value="$(awk -v key="$name" -F= '$1 == key {sub(/^[[:space:]]*/, "", $2); sub(/[[:space:]]*$/, "", $2); print $2; exit}' "$SECRET_FILE")"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
  fi
  [[ -n "$value" ]] || return 1
  printf '%s' "$value"
}

STAGING_EMAIL="$(read_secret STAGING_EMAIL || true)"
STAGING_PASSWORD="$(read_secret STAGING_PASSWORD || true)"
STAGING_OPENROUTER_KEY="$(read_secret STAGING_OPENROUTER_KEY || true)"
STAGING_SECONDARY_OPENROUTER_KEY="$(read_secret STAGING_SECONDARY_OPENROUTER_KEY || true)"
STAGING_PRIMARY_LABEL="$(read_secret STAGING_PRIMARY_LABEL || true)"
STAGING_SECONDARY_LABEL="$(read_secret STAGING_SECONDARY_LABEL || true)"
STAGING_PRIMARY_LABEL="${STAGING_PRIMARY_LABEL:-full-refactor-staging-primary}"
STAGING_SECONDARY_LABEL="${STAGING_SECONDARY_LABEL:-full-refactor-staging-secondary}"

mkdir -p "$(dirname "$REPORT")"
cookie_jar="$(mktemp)"
response_body="$(mktemp)"
response_headers="$(mktemp)"
sse_body="$(mktemp)"
trap 'rm -f "$cookie_jar" "$response_body" "$response_headers" "$sse_body"' EXIT

record() {
  local check="$1" status="$2" request_id="${3:-}" latency_ms="${4:-0}" attempts="${5:-1}" error_code="${6:-}"
  jq -cn \
    --arg check "$check" --arg status "$status" --arg request_id "$request_id" \
    --arg origin "$BACKEND_ORIGIN" --arg thread_id "$THREAD_ID" \
    --argjson latency_ms "$latency_ms" --argjson attempts "$attempts" \
    --arg error_code "$error_code" \
    '{check:$check,status:$status,backend_origin:$origin,thread_id:$thread_id,request_id:$request_id,latency_ms:$latency_ms,attempts:$attempts,error_code:$error_code}' \
    >> "$REPORT"
}

request() {
  local method="$1" path="$2" payload="${3:-}" csrf="${4:-}" started ended
  started="$(date +%s)"
  local -a args=(curl --silent --show-error --max-time "$TIMEOUT_SECONDS" --output "$response_body" --dump-header "$response_headers" --write-out '%{http_code}' -X "$method" "$BACKEND_ORIGIN$path" -b "$cookie_jar" -c "$cookie_jar" -H 'Accept: application/json')
  [[ -n "$payload" ]] && args+=( -H 'Content-Type: application/json' --data "$payload" )
  [[ -n "$csrf" ]] && args+=( -H "X-CSRF-Token: $csrf" )
  local code
  code="$("${args[@]}" 2>/dev/null || true)"
  ended="$(date +%s)"
  REQUEST_CODE="$code"
  REQUEST_LATENCY_MS=$(((ended - started) * 1000))
  REQUEST_ID="$(awk 'BEGIN{IGNORECASE=1} /^x-request-id:/ {gsub("\r", "", $2); print $2; exit}' "$response_headers")"
}

csrf_token() {
  awk '$6 == "app_csrf" {print $7; exit}' "$cookie_jar"
}

health_check() {
  request GET /health
  [[ "$REQUEST_CODE" == "200" ]] || { record health NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  record health VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
}

secret_bundle_available() {
  [[ -n "$STAGING_EMAIL" && -n "$STAGING_PASSWORD" ]]
}

login() {
  local payload
  payload="$(jq -cn --arg email "$STAGING_EMAIL" --arg password "$STAGING_PASSWORD" '{email:$email,password:$password}')"
  request POST /api/v1/auth/register "$payload" || true
  if [[ "$REQUEST_CODE" != "201" && "$REQUEST_CODE" != "409" ]]; then
    record register NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
    return 1
  fi
  record register VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
  request POST /api/v1/auth/login "$payload"
  [[ "$REQUEST_CODE" == "200" ]] || { record login NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  CSRF_TOKEN="$(csrf_token)"
  [[ -n "$CSRF_TOKEN" ]] || { record login NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_csrf_cookie; return 1; }
  record login VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
}

ensure_key() {
  local label="$1" raw_key="${2:-}" key_id
  request GET /api/v1/llm/provider-keys
  [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  key_id="$(jq -r --arg label "$label" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
  if [[ -z "$key_id" || "$key_id" == "null" ]]; then
    [[ -n "$raw_key" ]] || { record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_raw_key; return 0; }
    local payload
    payload="$(jq -cn --arg key "$raw_key" --arg label "$label" '{api_key:$key,label:$label}')"
    request POST /api/v1/llm/provider-keys "$payload" "$CSRF_TOKEN"
    [[ "$REQUEST_CODE" == "201" ]] || { record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
    key_id="$(jq -r '.id // empty' "$response_body")"
  fi
  [[ -n "$key_id" && "$key_id" != "null" ]] || { record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_key_id; return 1; }
  request POST "/api/v1/llm/provider-keys/$key_id/test" "" "$CSRF_TOKEN"
  local status
  status="$(jq -r '.status // "unknown"' "$response_body" 2>/dev/null || printf 'unknown')"
  if [[ "$REQUEST_CODE" == "200" ]] && [[ "$status" == "healthy" ]]; then
    record "key_$label" VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
    printf '%s' "$key_id"
    return 0
  fi
  record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "key_${status}"
  return 1
}

completion() {
  local run_payload run_id event_count terminal_count attempt=1
  run_payload="$(jq -cn --arg message "${STAGING_COMPLETION_MESSAGE:-Analyze the valuation workflow for AAPL and return a concise result.}" '{message:$message}')"
  while (( attempt <= RETRY_ATTEMPTS )); do
    request POST "/api/v1/threads/$THREAD_ID/runs" "$run_payload" "$CSRF_TOKEN"
    run_id="$(jq -r '.run_id // empty' "$response_body" 2>/dev/null || true)"
    if [[ "$REQUEST_CODE" == "202" ]]; then
      record completion_start VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt"
      break
    fi
    record completion_start RETRY "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" "http_$REQUEST_CODE"
    attempt=$((attempt + 1))
    sleep "$attempt"
  done
  [[ -n "$run_id" ]] || { record completion NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$RETRY_ATTEMPTS" retry_exhausted; return 1; }
  curl --silent --show-error --max-time "$TIMEOUT_SECONDS" --output "$sse_body" -N \
    -H 'Accept: text/event-stream' -H "Last-Event-ID: 0" -b "$cookie_jar" \
    "$BACKEND_ORIGIN/api/v1/threads/$THREAD_ID/events?run_id=$run_id&after_seq=0" >/dev/null || true
  event_count="$(awk '/^event: / {count++} END {print count+0}' "$sse_body")"
  terminal_count="$(
    awk '/^data: / {sub(/^data: /, ""); print}' "$sse_body" |
      jq -s --arg run_id "$run_id" '[.[] | select(.event_name == "workflow.activity" and .run_id == $run_id and .payload.run_id == $run_id and (.payload.status == "completed" or .payload.status == "failed" or .payload.status == "cancelled"))] | length'
  )"
  if (( event_count > 0 && terminal_count > 0 )); then
    record completion VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt"
  else
    record completion NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" no_terminal_event
    return 1
  fi
}

if ! health_check; then
  echo "Staging smoke health check failed; report: $REPORT" >&2
  exit 1
fi

if ! secret_bundle_available; then
  record live_provider INCONCLUSIVE "" 0 1 missing_secret_bundle
  record failover INCONCLUSIVE "" 0 1 missing_secret_bundle
  echo "Staging smoke recorded health and an inconclusive live-provider gate; no secret bundle was available. Report: $REPORT"
  exit 0
fi

login
primary_key_id="$(ensure_key "$STAGING_PRIMARY_LABEL" "$STAGING_OPENROUTER_KEY")"
secondary_key_id="$(ensure_key "$STAGING_SECONDARY_LABEL" "$STAGING_SECONDARY_OPENROUTER_KEY" || true)"
completion

if [[ -n "$primary_key_id" && -n "$secondary_key_id" ]]; then
  record failover INCONCLUSIVE "" 0 1 "requires_explicit_primary_fault_injection"
else
  record failover INCONCLUSIVE "" 0 1 missing_secondary_or_primary_key
fi

echo "Staging smoke completed; report: $REPORT"
