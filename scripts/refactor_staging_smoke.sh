#!/usr/bin/env bash
set -euo pipefail

# Re-runnable staging probe for the canonical /api/v1 contract. The script
# deliberately keeps provider responses in temporary files and records only
# masked metadata in the report.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SECRET_FILE="${STAGING_SECRET_FILE:-$ROOT/.env}"
REPORT="${STAGING_SMOKE_REPORT:-$ROOT/.audit/refactor-staging-smoke.jsonl}"
TIMEOUT_SECONDS="${STAGING_SMOKE_TIMEOUT_SECONDS:-90}"
COMPLETION_WAIT_SECONDS="${STAGING_COMPLETION_WAIT_SECONDS:-600}"
COMPLETION_POLL_SECONDS="${STAGING_COMPLETION_POLL_SECONDS:-5}"
RETRY_ATTEMPTS="${STAGING_SMOKE_RETRY_ATTEMPTS:-3}"
KEY_IMPORT_WAIT_SECONDS="${STAGING_KEY_IMPORT_WAIT_SECONDS:-90}"
KEY_IMPORT_POLL_SECONDS="${STAGING_KEY_IMPORT_POLL_SECONDS:-2}"
REQUIRE_LIVE_PROVIDER="${STAGING_REQUIRE_LIVE_PROVIDER:-0}"
STAGING_KEY_IMPORT_FILE="${STAGING_KEY_IMPORT_FILE:-}"
THREAD_ID="refactor-smoke-$(date -u +%Y%m%d%H%M%S)-$$"

for command in curl jq awk sed head mktemp date; do
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
    value="$(awk -v key="$name" '
      index($0, "=") > 0 && substr($0, 1, index($0, "=") - 1) == key {
        value = substr($0, index($0, "=") + 1)
        sub(/^[[:space:]]*/, "", value)
        sub(/[[:space:]]*$/, "", value)
        print value
        exit
      }
    ' "$SECRET_FILE")"
    value="${value#\"}"
    value="${value%\"}"
    value="${value#\'}"
    value="${value%\'}"
  fi
  [[ -n "$value" ]] || return 1
  printf '%s' "$value"
}

STAGING_BASE_URL="$(read_secret STAGING_BASE_URL || true)"
BACKEND_HOST_PORT="$(read_secret BACKEND_HOST_PORT || true)"
BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8000}"
BACKEND_ORIGIN="${STAGING_BASE_URL:-http://127.0.0.1:${BACKEND_HOST_PORT}}"
BACKEND_ORIGIN="${BACKEND_ORIGIN%/}"
STAGING_EMAIL="$(read_secret STAGING_EMAIL || true)"
STAGING_PASSWORD="$(read_secret STAGING_PASSWORD || true)"
STAGING_OPENROUTER_KEY="$(read_secret STAGING_OPENROUTER_KEY || true)"
STAGING_SECONDARY_OPENROUTER_KEY="$(read_secret STAGING_SECONDARY_OPENROUTER_KEY || true)"
STAGING_PRIMARY_LABEL="$(read_secret STAGING_PRIMARY_LABEL || true)"
STAGING_SECONDARY_LABEL="$(read_secret STAGING_SECONDARY_LABEL || true)"
STAGING_PRIMARY_LABEL="${STAGING_PRIMARY_LABEL:-full-refactor-staging-primary}"
STAGING_SECONDARY_LABEL="${STAGING_SECONDARY_LABEL:-full-refactor-staging-secondary}"
primary_key_id=""
secondary_key_id=""

mkdir -p "$(dirname "$REPORT")"
cookie_jar="$(mktemp)"
response_body="$(mktemp)"
response_headers="$(mktemp)"
trap 'rm -f "$cookie_jar" "$response_body" "$response_headers"' EXIT

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

request_file() {
  local method="$1" path="$2" file="$3" csrf="${4:-}" idempotency_key="${5:-}" started ended
  started="$(date +%s)"
  local -a args=(curl --silent --show-error --max-time "$TIMEOUT_SECONDS" --output "$response_body" --dump-header "$response_headers" --write-out '%{http_code}' -X "$method" "$BACKEND_ORIGIN$path" -b "$cookie_jar" -c "$cookie_jar" -H 'Accept: application/json' -F "file=@$file")
  [[ -n "$csrf" ]] && args+=( -H "X-CSRF-Token: $csrf" )
  [[ -n "$idempotency_key" ]] && args+=( -H "Idempotency-Key: $idempotency_key" )
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
  [[ -n "$STAGING_EMAIL" && -n "$STAGING_PASSWORD" ]] || return 1
  if [[ -n "$STAGING_KEY_IMPORT_FILE" ]]; then
    [[ -f "$STAGING_KEY_IMPORT_FILE" ]]
    return
  fi
  if [[ "$REQUIRE_LIVE_PROVIDER" == "1" ]]; then
    [[ -n "$STAGING_OPENROUTER_KEY" && -n "$STAGING_SECONDARY_OPENROUTER_KEY" ]]
  fi
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
  local label="$1" raw_key="${2:-}" key_id batch_id import_status item_status import_error deadline
  request GET /api/v1/llm/provider-keys
  [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  key_id="$(jq -r --arg label "$label" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
  if [[ -z "$key_id" || "$key_id" == "null" ]]; then
    [[ -n "$raw_key" ]] || { record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_raw_key; return 0; }
    local payload
    payload="$(jq -cn --arg key "$raw_key" --arg label "$label" '{api_key:$key,label:$label}')"
    request POST /api/v1/llm/provider-keys "$payload" "$CSRF_TOKEN"
    [[ "$REQUEST_CODE" == "202" ]] || { record "key_import_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
    batch_id="$(jq -r '.id // empty' "$response_body")"
    [[ -n "$batch_id" ]] || { record "key_import_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_batch_id; return 1; }

    deadline=$((SECONDS + KEY_IMPORT_WAIT_SECONDS))
    while :; do
      request GET "/api/v1/llm/provider-keys/imports/$batch_id"
      if [[ "$REQUEST_CODE" != "200" ]]; then
        record "key_import_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "poll_http_$REQUEST_CODE"
        return 1
      fi
      import_status="$(jq -r '.status // "unknown"' "$response_body")"
      if [[ "$import_status" == "completed" || "$import_status" == "completed_with_errors" ]]; then
        break
      fi
      if (( SECONDS >= deadline )); then
        record "key_import_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "import_timeout_${import_status}"
        return 1
      fi
      sleep "$KEY_IMPORT_POLL_SECONDS"
    done

    item_status="$(jq -r '.items[0].status // "unknown"' "$response_body")"
    if [[ "$import_status" != "completed" || "$item_status" != "imported" ]]; then
      import_error="$(jq -r '.items[0].error_code // .items[0].status // "unknown"' "$response_body")"
      record "key_import_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "$import_error"
      return 1
    fi
    record "key_import_$label" VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"

    request GET /api/v1/llm/provider-keys
    [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
    key_id="$(jq -r --arg label "$label" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
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

test_key_label() {
  local label="$1" key_id status
  request GET /api/v1/llm/provider-keys
  [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  key_id="$(jq -r --arg label "$label" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
  [[ -n "$key_id" && "$key_id" != "null" ]] || { record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_key_id; return 1; }
  request POST "/api/v1/llm/provider-keys/$key_id/test" "" "$CSRF_TOKEN"
  status="$(jq -r '.status // "unknown"' "$response_body" 2>/dev/null || printf 'unknown')"
  if [[ "$REQUEST_CODE" == "200" ]] && [[ "$status" == "healthy" ]]; then
    record "key_$label" VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
    printf '%s' "$key_id"
    return 0
  fi
  record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "key_${status}"
  return 1
}

batch_import_file() {
  local batch_id import_status imported_count invalid_count duplicate_count retryable_count expected_count deadline
  [[ -f "$STAGING_KEY_IMPORT_FILE" ]] || { record key_import_batch NOT_VERIFIED "" 0 1 missing_import_file; return 1; }
  expected_count="$(awk -F, 'NR > 1 { gsub(/^[[:space:]\"]+|[[:space:]\"]+$/, "", $1); if ($1 != "") count++ } END { print count + 0 }' "$STAGING_KEY_IMPORT_FILE")"
  [[ "$expected_count" =~ ^[1-9][0-9]*$ ]] || { record key_import_batch NOT_VERIFIED "" 0 1 empty_import_file; return 1; }
  request_file POST /api/v1/llm/provider-keys/imports "$STAGING_KEY_IMPORT_FILE" "$CSRF_TOKEN" "staging-smoke-$(date +%s)-$$"
  [[ "$REQUEST_CODE" == "202" ]] || { record key_import_batch NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  batch_id="$(jq -r '.id // empty' "$response_body")"
  [[ -n "$batch_id" ]] || { record key_import_batch NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_batch_id; return 1; }
  deadline=$((SECONDS + KEY_IMPORT_WAIT_SECONDS))
  while :; do
    request GET "/api/v1/llm/provider-keys/imports/$batch_id"
    [[ "$REQUEST_CODE" == "200" ]] || { record key_import_batch NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "poll_http_$REQUEST_CODE"; return 1; }
    import_status="$(jq -r '.status // "unknown"' "$response_body")"
    [[ "$import_status" == "completed" || "$import_status" == "completed_with_errors" ]] && break
    if (( SECONDS >= deadline )); then
      record key_import_batch NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "import_timeout_${import_status}"
      return 1
    fi
    sleep "$KEY_IMPORT_POLL_SECONDS"
  done
  imported_count="$(jq -r '.imported_count // 0' "$response_body")"
  invalid_count="$(jq -r '.invalid_count // 0' "$response_body")"
  duplicate_count="$(jq -r '.duplicate_count // 0' "$response_body")"
  retryable_count="$(jq -r '.retryable_count // 0' "$response_body")"
  if [[ "$import_status" != "completed" && "$import_status" != "completed_with_errors" ]] || (( imported_count + duplicate_count != expected_count )) || [[ "$invalid_count" != "0" || "$retryable_count" != "0" ]]; then
    record key_import_batch NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "status_${import_status}_expected_${expected_count}_imported_${imported_count}_invalid_${invalid_count}_duplicates_${duplicate_count}_retryable_${retryable_count}"
    return 1
  fi
  record key_import_batch VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "expected_${expected_count}_imported_${imported_count}_duplicates_${duplicate_count}"
}

completion() {
  local run_payload run_id="" event_count run_status selection_identity selection_payload approval_count workflow_waiting_count calculation_count artifact_ids artifact_id artifact_count artifact_failures attempt=1 deadline
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
  deadline=$((SECONDS + COMPLETION_WAIT_SECONDS))
  while :; do
    request GET "/api/v1/threads/$THREAD_ID/activities?run_id=$run_id"
    if [[ "$REQUEST_CODE" != "200" ]]; then
      record completion NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" "snapshot_http_$REQUEST_CODE"
      return 1
    fi
    run_status="$(jq -r '.run_status // "unknown"' "$response_body")"
    selection_identity="$(jq -c '.pending_interactions[]? | select(.kind == "ticker_selection" and .status == "pending") | .identity' "$response_body" | head -n1)"
    if [[ -n "$selection_identity" ]]; then
      selection_payload="$(jq -cn --argjson identity "$selection_identity" '{identity:$identity,response:{type:"ticker_selection",selected_symbol:"AAPL"}}')"
      request POST "/api/v1/threads/$THREAD_ID/runs/$run_id/resume" "$selection_payload" "$CSRF_TOKEN"
      [[ "$REQUEST_CODE" == "202" ]] || { record ticker_selection_response NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
      record ticker_selection_response VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
      continue
    fi
    approval_count="$(jq '[.pending_interactions[]? | select(.kind == "valuation_approval" and .status == "pending")] | length' "$response_body")"
    if [[ "$run_status" == "waiting" ]] && (( approval_count > 0 )); then break; fi
    [[ "$run_status" == "failed" || "$run_status" == "cancelled" ]] && break
    if (( SECONDS >= deadline )); then
      record completion NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" "completion_timeout_${run_status}"
      return 1
    fi
    sleep "$COMPLETION_POLL_SECONDS"
  done

  event_count="$(jq -r '.cursor // 0' "$response_body")"
  approval_count="$(jq '[.pending_interactions[]? | select(.kind == "valuation_approval" and .status == "pending")] | length' "$response_body")"
  workflow_waiting_count="$(jq '[.active_activities[]? | select(.status == "waiting" and ([.scope_path[]? | ascii_downcase | contains("calculation")] | any))] | length' "$response_body")"
  calculation_count="$(jq '([.active_activities[]? | select(((.activity_id // "") | ascii_downcase | contains("calculat")) or ([.scope_path[]? | ascii_downcase | contains("calculat")] | any)) | select(.status != "waiting")] + [.recent_activities[]? | select(((.activity_id // "") | ascii_downcase | contains("calculat")) or ([.scope_path[]? | ascii_downcase | contains("calculat")] | any)) | select(.status == "completed")]) | length' "$response_body")"
  run_status="$(jq -r '.run_status // "unknown"' "$response_body")"
  artifact_ids="$(jq -r --arg run_id "$run_id" '[.completed_outputs[]? | select(.identity.run_id == $run_id) | .artifact_id // empty] | unique | .[]' "$response_body")"
  artifact_count="$(jq -r --arg run_id "$run_id" '[.completed_outputs[]? | select(.identity.run_id == $run_id and .artifact_id != null)] | length' "$response_body")"
  artifact_failures=0

  while IFS= read -r artifact_id; do
    [[ -n "$artifact_id" ]] || continue
    request GET "/api/v1/artifacts/$artifact_id?run_id=$run_id"
    if [[ "$REQUEST_CODE" != "200" ]] || ! jq -e 'type == "object" and has("data")' "$response_body" >/dev/null; then
      artifact_failures=$((artifact_failures + 1))
    fi
  done <<< "$artifact_ids"

  if (( event_count > 0 && approval_count > 0 && workflow_waiting_count > 0 && calculation_count == 0 )) && [[ "$run_status" == "waiting" ]] && (( artifact_failures == 0 )); then
    record valuation_approval VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt"
    record completion VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt"
  else
    local error_code="run_status_${run_status}"
    if (( event_count == 0 )); then error_code="no_workflow_events"; fi
    if (( approval_count == 0 )); then error_code="missing_pending_valuation_approval"; fi
    if (( workflow_waiting_count == 0 )); then error_code="workflow_not_waiting"; fi
    if (( calculation_count > 0 )); then error_code="calculation_activity_detected"; fi
    if (( artifact_failures > 0 )); then error_code="artifact_fetch_failed"; fi
    record completion NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" "$error_code"
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
  if [[ "$REQUIRE_LIVE_PROVIDER" == "1" ]]; then
    echo "Staging smoke requires both staging OpenRouter keys and account credentials; report: $REPORT" >&2
    exit 1
  fi
  echo "Staging smoke recorded health and an inconclusive live-provider gate; no secret bundle was available. Report: $REPORT"
  exit 0
fi

login
if [[ -n "$STAGING_KEY_IMPORT_FILE" ]]; then
  batch_import_file
  expected_key_count="$(awk -F, 'NR > 1 { gsub(/^[[:space:]\"]+|[[:space:]\"]+$/, "", $1); if ($1 != "") count++ } END { print count + 0 }' "$STAGING_KEY_IMPORT_FILE")"
  tested_key_count=0
  while IFS= read -r label; do
    [[ -n "$label" ]] || continue
    test_key_label "$label" >/dev/null
    tested_key_count=$((tested_key_count + 1))
  done < <(awk -F, 'NR > 1 {gsub(/^[[:space:]\"]+|[[:space:]\"]+$/, "", $2); if ($2 != "") print $2}' "$STAGING_KEY_IMPORT_FILE")
  if (( tested_key_count != expected_key_count )); then
    record key_import_batch NOT_VERIFIED "" 0 1 "tested_${tested_key_count}_of_${expected_key_count}"
    exit 1
  fi
else
  primary_key_id="$(ensure_key "$STAGING_PRIMARY_LABEL" "$STAGING_OPENROUTER_KEY")"
  secondary_key_id="$(ensure_key "$STAGING_SECONDARY_LABEL" "$STAGING_SECONDARY_OPENROUTER_KEY")"
fi
completion

if [[ -n "$STAGING_KEY_IMPORT_FILE" ]]; then
  record failover INCONCLUSIVE "" 0 1 "requires_explicit_primary_fault_injection"
elif [[ -n "$primary_key_id" && -n "$secondary_key_id" ]]; then
  record failover INCONCLUSIVE "" 0 1 "requires_explicit_primary_fault_injection"
else
  record failover INCONCLUSIVE "" 0 1 missing_secondary_or_primary_key
fi

echo "Staging smoke completed; report: $REPORT"
