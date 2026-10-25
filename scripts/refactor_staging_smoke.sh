#!/usr/bin/env bash
set -euo pipefail

# Re-runnable staging probe for the canonical /api/v1 contract. The script
# deliberately keeps provider responses in temporary files and records only
# masked metadata in the report.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

worktree_value() {
  local name="$1"
  [[ -f "$ROOT/.env" ]] || return 1
  awk -v key="$name" -F= '$1 == key {sub(/^[[:space:]]*/, "", $2); sub(/[[:space:]]*$/, "", $2); print $2; exit}' "$ROOT/.env"
}

BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-$(worktree_value BACKEND_HOST_PORT || true)}"
BACKEND_HOST_PORT="${BACKEND_HOST_PORT:-8000}"
BACKEND_ORIGIN="${STAGING_BASE_URL:-http://127.0.0.1:${BACKEND_HOST_PORT}}"
BACKEND_ORIGIN="${BACKEND_ORIGIN%/}"
LLM_PROVIDER_SERVICE_HOST_PORT="${LLM_PROVIDER_SERVICE_HOST_PORT:-$(worktree_value LLM_PROVIDER_SERVICE_HOST_PORT || true)}"
LLM_PROVIDER_SERVICE_HOST_PORT="${LLM_PROVIDER_SERVICE_HOST_PORT:-8002}"
LLM_PROVIDER_ORIGIN="http://127.0.0.1:${LLM_PROVIDER_SERVICE_HOST_PORT}"
SECRET_FILE="${STAGING_SECRET_FILE:-$ROOT/.env}"
REPORT="${STAGING_SMOKE_REPORT:-$ROOT/.audit/refactor-staging-smoke.jsonl}"
TIMEOUT_SECONDS="${STAGING_SMOKE_TIMEOUT_SECONDS:-300}"
RETRY_ATTEMPTS="${STAGING_SMOKE_RETRY_ATTEMPTS:-3}"
SMOKE_MODE="${STAGING_SMOKE_MODE:-provider-probe}"
BASE_THREAD_ID="refactor-smoke-$(date -u +%Y%m%d%H%M%S)-$$"
THREAD_ID="$BASE_THREAD_ID"
PRIMARY_KEY_ID=""
SECONDARY_KEY_ID=""
PRIMARY_KEY_READY=0
SECONDARY_KEY_READY=0
PRIMARY_KEY_FINGERPRINT=""
SECONDARY_KEY_FINGERPRINT=""
ENSURED_KEY_ID=""
ENSURED_KEY_FINGERPRINT=""
PRIMARY_DELETED=0
LAST_COMPLETION_ATTEMPTS=1
LAST_COMPLETION_REQUEST_ID=""
LAST_COMPLETION_LATENCY_MS=0
LAST_COMPLETION_ATTRIBUTION_FINGERPRINT=""
LAST_COMPLETION_ATTRIBUTION_DEPLOYMENT_ID=""
LAST_PROVIDER_RESULT_EVIDENCE='null'
LAST_PROVIDER_CALLS='[]'
LAST_PROVIDER_USAGE='null'
LAST_PROVIDER_RETRY_COUNT=0
LAST_PROVIDER_SUCCESS_COUNT=0
LAST_PROVIDER_EVIDENCE_AVAILABLE=0
SMOKE_FAILED=0
provider_log=""
ACTIVE_RUN_ID=""
ACTIVE_RUN_THREAD_ID=""

for command in curl jq awk sed mktemp date docker shasum; do
  command -v "$command" >/dev/null 2>&1 || {
    echo "required command is missing: $command" >&2
    exit 2
  }
done

jq() {
  local status=0
  command jq "$@" || status=$?
  if (( status != 0 )); then
    printf 'staging smoke jq failed at caller line %s (exit %s)\n' \
      "${BASH_LINENO[0]:-unknown}" "$status" >&2
  fi
  return "$status"
}

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
LLM_PROVIDER_SERVICE_TOKEN="${LLM_PROVIDER_SERVICE_TOKEN:-$(read_secret LLM_PROVIDER_SERVICE_TOKEN || worktree_value LLM_PROVIDER_SERVICE_TOKEN || true)}"
STAGING_PRIMARY_LABEL="$(read_secret STAGING_PRIMARY_LABEL || true)"
STAGING_SECONDARY_LABEL="$(read_secret STAGING_SECONDARY_LABEL || true)"
STAGING_COMPLETION_MODEL="${STAGING_COMPLETION_MODEL:-$(read_secret STAGING_COMPLETION_MODEL || true)}"
STAGING_RESUME_TICKER="${STAGING_RESUME_TICKER:-$(read_secret STAGING_RESUME_TICKER || true)}"
STAGING_PRIMARY_LABEL="${STAGING_PRIMARY_LABEL:-issue-97-staging-primary-replacement}"
STAGING_SECONDARY_LABEL="${STAGING_SECONDARY_LABEL:-issue-97-staging-secondary}"
STAGING_RESUME_TICKER="${STAGING_RESUME_TICKER:-AAPL}"
PREVIOUS_SELECTED_MODEL=""
MODEL_OVERRIDE_APPLIED=0

mkdir -p "$(dirname "$REPORT")"
cookie_jar="$(mktemp)"
response_body="$(mktemp)"
response_headers="$(mktemp)"
sse_body="$(mktemp)"
provider_log="$(mktemp)"
record() {
  local check="$1" status="$2" request_id="${3:-}" latency_ms="${4:-0}" attempts="${5:-1}" error_code="${6:-}"
  local provider_calls="${7:-[]}" usage="${8:-null}"
  local free_model_daily_requests="${9:-null}"
  local http_status="${10:-null}" key_fingerprint="${11:-}"
  local result_evidence="${12:-null}"
  local key_health="${13:-null}"
  jq -cn \
    --arg check "$check" --arg status "$status" --arg request_id "$request_id" \
    --arg origin "$BACKEND_ORIGIN" --arg thread_id "$THREAD_ID" \
    --argjson latency_ms "$latency_ms" --argjson attempts "$attempts" \
    --arg error_code "$error_code" --argjson provider_calls "$provider_calls" \
    --argjson usage "$usage" --argjson free_model_daily_requests "$free_model_daily_requests" \
    --argjson http_status "$http_status" --arg key_fingerprint "$key_fingerprint" \
    --argjson result_evidence "$result_evidence" \
    --argjson key_health "$key_health" \
    '{check:$check,status:$status,backend_origin:$origin,thread_id:$thread_id,request_id:$request_id,latency_ms:$latency_ms,attempts:$attempts,provider_calls:$provider_calls,usage:$usage,free_model_daily_requests:$free_model_daily_requests,http_status:$http_status,key_fingerprint:$key_fingerprint,result_evidence:$result_evidence,key_health:$key_health,error_code:$error_code}' \
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

compose_project_for_backend_port() {
  local backend_ids backend_id count service project
  backend_ids="$(docker ps --filter "publish=$BACKEND_HOST_PORT" --format '{{.ID}}' 2>/dev/null)"
  count="$(printf '%s\n' "$backend_ids" | awk 'NF {count++} END {print count+0}')"
  [[ "$count" == "1" ]] || return 1
  backend_id="$(printf '%s\n' "$backend_ids" | sed -n '1p')"
  service="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$backend_id" 2>/dev/null || true)"
  [[ "$service" == "backend" ]] || return 1
  project="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$backend_id" 2>/dev/null || true)"
  [[ -n "$project" ]] || return 1
  printf '%s' "$project"
}

provider_calls_since() {
  local started_at="$1" request_id="${2:-}" project
  project="$(compose_project_for_backend_port)" || return 1
  docker compose -p "$project" logs --no-color --no-log-prefix --since "$started_at" llm-provider-service > "$provider_log" 2>/dev/null || return 1
  jq -Rsc --arg request_id "$request_id" '
    [split("\n")[] | select(length > 0)
      | (try (match("\\{.*\\}$").string | fromjson) catch null)
      | select(. != null and .event == "llm_provider_request")
      | . as $event
      | ($event.fields // $event) as $fields
      | select($request_id == "" or ($fields.request_id // $event.request_id // "") == $request_id)
      | {
          request_id: ($fields.request_id // $event.request_id // null),
          operation: ($fields.operation // null),
          deployment_id: ($fields.deployment_id // null),
          key_fingerprint: ($fields.key_fingerprint // null),
          attempts: ($fields.attempts // 1),
          retry_count: ($fields.retry_count // 0),
          latency_ms: ($fields.latency_ms // null),
          usage: {
            prompt_tokens: ($fields.prompt_tokens // null),
            completion_tokens: ($fields.completion_tokens // null),
            total_tokens: ($fields.total_tokens // null)
          },
          error_code: ($event.error_code // null)
        }
    ]
  ' "$provider_log" 2>/dev/null
}

capture_provider_evidence() {
  local started_at="$1" request_id="${2:-}"
  LAST_PROVIDER_CALLS="$(provider_calls_since "$started_at" "$request_id")" || return 1
  if ! jq -e 'type == "array"' <<< "$LAST_PROVIDER_CALLS" >/dev/null 2>&1; then
    LAST_PROVIDER_CALLS='[]'
    return 1
  fi
  LAST_PROVIDER_RETRY_COUNT="$(jq -r '[.[] | .retry_count // 0] | max // 0' <<< "$LAST_PROVIDER_CALLS")"
  LAST_PROVIDER_SUCCESS_COUNT="$(jq -r '[.[] | select(.error_code == null and ((.deployment_id != null) or (.usage.total_tokens != null)))] | length' <<< "$LAST_PROVIDER_CALLS")"
  LAST_PROVIDER_REQUEST_ID="$(jq -r '
    . as $calls
    | ([ $calls[] | select((.retry_count // 0) > 0) ] | last | .request_id)
      // ([ $calls[] | select(.error_code == null and ((.deployment_id != null) or (.usage.total_tokens != null))) ] | last | .request_id)
      // ([ $calls[] ] | last | .request_id)
      // empty
  ' <<< "$LAST_PROVIDER_CALLS")"
  LAST_PROVIDER_USAGE="$(jq -cn --argjson calls "$LAST_PROVIDER_CALLS" '
    if ($calls | length) == 0 then null else
      {
        prompt_tokens: ([$calls[].usage.prompt_tokens | select(type == "number")] | if length > 0 then add else null end),
        completion_tokens: ([$calls[].usage.completion_tokens | select(type == "number")] | if length > 0 then add else null end),
        total_tokens: ([$calls[].usage.total_tokens | select(type == "number")] | if length > 0 then add else null end)
      }
    end
  ')"
}

restore_primary_key() {
  [[ "$PRIMARY_DELETED" == "1" ]] || return 0
  [[ -n "$STAGING_OPENROUTER_KEY" ]] || return 1
  local restored_id restored_fingerprint payload
  request GET /api/v1/llm/provider-keys
  if [[ "$REQUEST_CODE" != "200" ]]; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "list_http_$REQUEST_CODE"
    return 1
  fi
  if ! jq -e 'type == "array"' "$response_body" >/dev/null 2>&1; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 invalid_key_list_response
    return 1
  fi
  restored_id="$(jq -r --arg label "$STAGING_PRIMARY_LABEL" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
  if [[ -z "$restored_id" || "$restored_id" == "null" ]]; then
    payload="$(jq -cn --arg key "$STAGING_OPENROUTER_KEY" --arg label "$STAGING_PRIMARY_LABEL" '{api_key:$key,label:$label}')"
    request POST /api/v1/llm/provider-keys "$payload" "$CSRF_TOKEN"
    if [[ "$REQUEST_CODE" != "201" ]]; then
      record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
      return 1
    fi
    restored_id="$(jq -r '.id // empty' "$response_body" 2>/dev/null || true)"
  fi
  if [[ -z "$restored_id" ]]; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_key_id
    return 1
  fi
  request GET /api/v1/llm/provider-keys
  if [[ "$REQUEST_CODE" != "200" ]] || ! jq -e 'type == "array"' "$response_body" >/dev/null 2>&1; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 key_list_failed_after_restore
    return 1
  fi
  restored_fingerprint="$(jq -r --arg id "$restored_id" '.[] | select(.id == $id) | .fingerprint' "$response_body" | head -n1)"
  if [[ -z "$restored_fingerprint" || "$restored_fingerprint" == "null" ]]; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_key_fingerprint
    return 1
  fi
  if [[ -n "$PRIMARY_KEY_FINGERPRINT" && "$restored_fingerprint" != "$PRIMARY_KEY_FINGERPRINT" ]]; then
    record primary_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 key_fingerprint_mismatch
    return 1
  fi
  PRIMARY_KEY_ID="$restored_id"
  PRIMARY_KEY_FINGERPRINT="$restored_fingerprint"
  PRIMARY_DELETED=0
  record primary_restore VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
  return 0
}

restore_selected_model() {
  [[ "$MODEL_OVERRIDE_APPLIED" == "1" && -n "$PREVIOUS_SELECTED_MODEL" ]] || return 0
  local payload selected_model
  payload="$(jq -cn --arg selected_model "$PREVIOUS_SELECTED_MODEL" '{selected_model:$selected_model}')"
  request PUT /api/v1/llm/settings "$payload" "$CSRF_TOKEN"
  selected_model="$(jq -r '.selected_model // empty' "$response_body" 2>/dev/null || true)"
  if [[ "$REQUEST_CODE" == "200" && "$selected_model" == "$PREVIOUS_SELECTED_MODEL" ]]; then
    record model_restore VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
    MODEL_OVERRIDE_APPLIED=0
    return 0
  fi
  record model_restore NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
  return 1
}

cancel_active_run() {
  [[ -n "$ACTIVE_RUN_ID" ]] || return 0
  local snapshot_path run_status deadline run_thread_id="${ACTIVE_RUN_THREAD_ID:-$THREAD_ID}"
  snapshot_path="/api/v1/threads/$run_thread_id/activities"
  request GET "$snapshot_path"
  if [[ "$REQUEST_CODE" != "200" ]]; then
    record run_cleanup INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "snapshot_http_$REQUEST_CODE"
    return 1
  fi
  run_status="$(jq -r --arg run_id "$ACTIVE_RUN_ID" 'if .run_id == $run_id then (.run_status // "unknown") else "superseded" end' "$response_body")"
  if [[ "$run_status" == "completed" || "$run_status" == "failed" || "$run_status" == "cancelled" || "$run_status" == "superseded" ]]; then
    record run_cleanup VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "already_$run_status"
    ACTIVE_RUN_ID=""
    ACTIVE_RUN_THREAD_ID=""
    return 0
  fi
  if [[ "$run_status" != "queued" && "$run_status" != "running" && "$run_status" != "waiting" ]]; then
    record run_cleanup INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "run_$run_status"
    return 1
  fi

  request POST "/api/v1/threads/$run_thread_id/runs/$ACTIVE_RUN_ID/cancel" "" "$CSRF_TOKEN"
  if [[ "$REQUEST_CODE" != "204" ]]; then
    record run_cleanup NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "cancel_http_$REQUEST_CODE"
    return 1
  fi
  deadline=$(( $(date +%s) + ${STAGING_CLEANUP_TIMEOUT_SECONDS:-30} ))
  while (( $(date +%s) <= deadline )); do
    request GET "$snapshot_path"
    if [[ "$REQUEST_CODE" != "200" ]]; then
      record run_cleanup NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "snapshot_http_$REQUEST_CODE"
      return 1
    fi
    run_status="$(jq -r --arg run_id "$ACTIVE_RUN_ID" 'if .run_id == $run_id then (.run_status // "unknown") else "superseded" end' "$response_body")"
    if [[ "$run_status" == "completed" || "$run_status" == "failed" || "$run_status" == "cancelled" || "$run_status" == "superseded" ]]; then
      record run_cleanup VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "cancelled_as_$run_status"
      ACTIVE_RUN_ID=""
      ACTIVE_RUN_THREAD_ID=""
      return 0
    fi
    sleep 1
  done
  record run_cleanup NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 cancel_timeout
  return 1
}

capture_completion_evidence() {
  local started_at="$1" request_id="$2" latency_ms="$3" fallback_attempts="$4"
  LAST_COMPLETION_REQUEST_ID="$request_id"
  LAST_COMPLETION_LATENCY_MS="$latency_ms"
  if capture_provider_evidence "$started_at"; then
    LAST_PROVIDER_EVIDENCE_AVAILABLE=1
    LAST_COMPLETION_ATTEMPTS="$(jq -r '[.[] | .attempts // 1] | max // 1' <<< "$LAST_PROVIDER_CALLS")"
  else
    LAST_PROVIDER_EVIDENCE_AVAILABLE=0
    LAST_COMPLETION_ATTEMPTS="$fallback_attempts"
  fi
}

provider_completion() {
  local check_name="$1" user_id request_id deadline payload started_at started ended code valid_result error_code http_status_json
  if [[ -z "$LLM_PROVIDER_SERVICE_TOKEN" ]]; then
    record "$check_name" INCONCLUSIVE "" 0 1 missing_provider_service_token
    return 1
  fi
  request GET /api/v1/auth/me
  if [[ "$REQUEST_CODE" != "200" ]]; then
    record "$check_name" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "principal_http_$REQUEST_CODE"
    return 1
  fi
  user_id="$(jq -r '.user_id // empty' "$response_body" 2>/dev/null || true)"
  if [[ -z "$user_id" ]]; then
    record "$check_name" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_authenticated_principal
    return 1
  fi

  request_id="${BASE_THREAD_ID}-${check_name}"
  deadline="$(jq -nr 'now + 90 | todateiso8601')"
  payload="$(jq -cn \
    --arg user_id "$user_id" --arg request_id "$request_id" \
    --arg deadline "$deadline" \
    '{context:{principal:{subject_id:$user_id},correlation_id:$request_id,contract_version:"internal.v1",deadline_at:$deadline},input:{schema_version:"llm.v1",messages:[{role:"user",content:"Reply with the single word READY."}],route:{alias:"openrouter-default"},request_id:$request_id,operation:"staging.smoke",request_class:"interactive",temperature:0,max_tokens:256,timeout_seconds:60,idempotency_key:null,metadata:{source:"staging-smoke"},tools:[],tool_choice:null}}')"
  started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  started="$(date +%s)"
  code="$(printf 'url = "%s/v1/completions"\nheader = "Authorization: Bearer %s"\n' "$LLM_PROVIDER_ORIGIN" "$LLM_PROVIDER_SERVICE_TOKEN" | \
    curl --silent --show-error --max-time 90 --output "$response_body" \
      --dump-header "$response_headers" --write-out '%{http_code}' \
      --config - --request POST --header 'Content-Type: application/json' \
      --data-binary "$payload" 2>/dev/null || true)"
  ended="$(date +%s)"
  REQUEST_CODE="$code"
  REQUEST_LATENCY_MS=$(((ended - started) * 1000))
  http_status_json="null"
  [[ "$REQUEST_CODE" =~ ^[1-9][0-9]{2}$ ]] && http_status_json="$REQUEST_CODE"
  REQUEST_ID="$request_id"
  LAST_COMPLETION_REQUEST_ID="$request_id"
  LAST_COMPLETION_LATENCY_MS="$REQUEST_LATENCY_MS"
  LAST_PROVIDER_EVIDENCE_AVAILABLE=0
  LAST_PROVIDER_CALLS='[]'
  LAST_PROVIDER_USAGE="$(jq -c '.result.usage // null' "$response_body" 2>/dev/null || printf 'null')"
  LAST_COMPLETION_ATTRIBUTION_FINGERPRINT="$(jq -r '.result.attribution.key_fingerprint // ([.result.attempts[]? | select(.error_code == null and .key_fingerprint != null) | .key_fingerprint] | last // empty)' "$response_body" 2>/dev/null || true)"
  LAST_COMPLETION_ATTRIBUTION_DEPLOYMENT_ID="$(jq -r '.result.attribution.deployment_id // ([.result.attempts[]? | select(.error_code == null and .deployment_id != null) | .deployment_id] | last // empty)' "$response_body" 2>/dev/null || true)"
  LAST_PROVIDER_RESULT_EVIDENCE="$(jq -c --arg request_id "$request_id" '
    if (.result | type) != "object" then null else
      {
        model: (.result.model // null),
        request_id_matches: (.result.request_id == $request_id),
        text_length: ((.result.text // "") | if type == "string" then length else null end),
        finish_reason: (.result.finish_reason // null),
        attribution: (.result.attribution // null),
        attempts: [(.result.attempts // [])[] | {attempt,key_fingerprint,deployment_id,error_code}]
      }
    end
  ' "$response_body" 2>/dev/null || printf 'null')"
  if capture_provider_evidence "$started_at" "$request_id"; then
    LAST_PROVIDER_EVIDENCE_AVAILABLE=1
    LAST_COMPLETION_ATTEMPTS="$(jq -r '[.[] | .attempts // 1] | max // 1' <<< "$LAST_PROVIDER_CALLS")"
  else
    LAST_COMPLETION_ATTEMPTS=1
    LAST_PROVIDER_RETRY_COUNT=0
    LAST_PROVIDER_SUCCESS_COUNT=0
    LAST_PROVIDER_REQUEST_ID="$request_id"
  fi
  valid_result="$(jq -e --arg request_id "$request_id" '.result | (.request_id == $request_id and (.text | type == "string" and length > 0) and .finish_reason != "length")' "$response_body" >/dev/null 2>&1 && printf 'true' || printf 'false')"
  if [[ "$REQUEST_CODE" == "200" && "$valid_result" == "true" ]]; then
    record "$check_name" VERIFIED "$request_id" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE" null "$http_status_json" "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" "$LAST_PROVIDER_RESULT_EVIDENCE"
    return 0
  fi
  error_code="$(jq -r '.error.code // "provider_http_failure"' "$response_body" 2>/dev/null | awk '/^[a-z0-9_]+$/ {print; found=1} END {if (!found) print "provider_http_failure"}')"
  if [[ "$error_code" == "provider_http_failure" && "$REQUEST_CODE" =~ ^[1-9][0-9]{2}$ ]]; then
    if [[ "$REQUEST_CODE" == "200" ]]; then
      error_code="$(jq -r 'if (.result | type) != "object" then "malformed_completion_result" elif .result.finish_reason == "length" then "completion_truncated" elif (.result.text // "") == "" then "empty_completion_result" else "invalid_completion_result" end' "$response_body" 2>/dev/null || printf 'invalid_completion_result')"
    else
      error_code="provider_http_$REQUEST_CODE"
    fi
  fi
  record "$check_name" NOT_VERIFIED "$request_id" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "$error_code" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE" null "$http_status_json" "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" "$LAST_PROVIDER_RESULT_EVIDENCE"
  return 1
}

fail_completion() {
  local check_name="$1" failure_code="$2" started_at="$3" request_id="$4" latency_ms="$5" attempts="$6"
  cancel_active_run || true
  capture_completion_evidence "$started_at" "$request_id" "$latency_ms" "$attempts"
  record "$check_name" NOT_VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "$failure_code" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
  return 1
}

cleanup_primary() {
  local status=$?
  trap - EXIT
  cancel_active_run || status=1
  restore_primary_key || status=1
  restore_selected_model || status=1
  rm -f "$cookie_jar" "$response_body" "$response_headers" "$sse_body" "$provider_log"
  exit "$status"
}

trap cleanup_primary EXIT

secret_bundle_available() {
  [[ -n "$STAGING_EMAIL" && -n "$STAGING_PASSWORD" ]]
}

login() {
  local payload
  payload="$(jq -cn --arg email "$STAGING_EMAIL" --arg password "$STAGING_PASSWORD" '{email:$email,password:$password}')"
  if [[ "$SMOKE_MODE" != "keys-only" ]]; then
    request POST /api/v1/auth/register "$payload" || true
    if [[ "$REQUEST_CODE" != "201" && "$REQUEST_CODE" != "409" ]]; then
      record register NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
      return 1
    fi
    record register VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
  fi
  request POST /api/v1/auth/login "$payload"
  [[ "$REQUEST_CODE" == "200" ]] || { record login NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  CSRF_TOKEN="$(csrf_token)"
  [[ -n "$CSRF_TOKEN" ]] || { record login NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_csrf_cookie; return 1; }
  record login VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
}

select_completion_model() {
  [[ -n "$STAGING_COMPLETION_MODEL" ]] || return 0
  request GET /api/v1/llm/settings
  [[ "$REQUEST_CODE" == "200" ]] || {
    record model_override NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
    return 1
  }
  PREVIOUS_SELECTED_MODEL="$(jq -r '.selected_model // empty' "$response_body")"
  [[ -n "$PREVIOUS_SELECTED_MODEL" ]] || {
    record model_override NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_current_model
    return 1
  }
  [[ "$PREVIOUS_SELECTED_MODEL" == "$STAGING_COMPLETION_MODEL" ]] && return 0
  local payload selected_model
  payload="$(jq -cn --arg selected_model "$STAGING_COMPLETION_MODEL" '{selected_model:$selected_model}')"
  request PUT /api/v1/llm/settings "$payload" "$CSRF_TOKEN"
  selected_model="$(jq -r '.selected_model // empty' "$response_body" 2>/dev/null || true)"
  if [[ "$REQUEST_CODE" == "200" && "$selected_model" == "$STAGING_COMPLETION_MODEL" ]]; then
    MODEL_OVERRIDE_APPLIED=1
    record model_override VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"
    return 0
  fi
  record model_override NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
  return 1
}

ensure_key() {
  local label="$1" raw_key="${2:-}" key_id
  ENSURED_KEY_ID=""
  ENSURED_KEY_FINGERPRINT=""
  request GET /api/v1/llm/provider-keys
  [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  if ! jq -e 'type == "array"' "$response_body" >/dev/null 2>&1; then
    record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 invalid_key_list_response
    return 1
  fi
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
  ENSURED_KEY_ID="$key_id"
  request GET /api/v1/llm/provider-keys
  [[ "$REQUEST_CODE" == "200" ]] || { record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"; return 1; }
  if ! jq -e 'type == "array"' "$response_body" >/dev/null 2>&1; then
    record key_list NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 invalid_key_list_response
    return 1
  fi
  ENSURED_KEY_FINGERPRINT="$(jq -r --arg id "$key_id" '.[] | select(.id == $id) | .fingerprint' "$response_body" | head -n1)"
  [[ -n "$ENSURED_KEY_FINGERPRINT" && "$ENSURED_KEY_FINGERPRINT" != "null" ]] || {
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_key_fingerprint
    return 1
  }
  local raw_fingerprint
  raw_fingerprint="$(printf '%s' "$raw_key" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
  if [[ -z "$raw_key" || "$raw_fingerprint" != "$ENSURED_KEY_FINGERPRINT" ]]; then
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 saved_key_fingerprint_mismatch
    return 1
  fi
  local key_health
  key_health="$(jq -c --arg id "$key_id" '.[] | select(.id == $id) | {id,status,failure_count,cooldown_until,last_error,last_used_at}' "$response_body" | head -n1)"
  check_openrouter_key_account "$label" "$raw_key" "${key_health:-null}"
}

check_openrouter_key_account() {
  local label="$1" raw_key="$2" key_health="${3:-null}" started ended code quota
  started="$(date +%s)"
  code="$(printf 'url = "https://openrouter.ai/api/v1/key"\nheader = "Authorization: Bearer %s"\n' "$raw_key" | \
    curl --silent --show-error --max-time 15 --output "$response_body" \
      --dump-header "$response_headers" --write-out '%{http_code}' --config - 2>/dev/null || true)"
  ended="$(date +%s)"
  REQUEST_CODE="$code"
  REQUEST_LATENCY_MS=$(((ended - started) * 1000))
  REQUEST_ID="$(awk 'BEGIN{IGNORECASE=1} /^x-request-id:/ {gsub("\r", "", $2); print $2; exit}' "$response_headers")"
  quota="$(jq -ce '.data.free_model_daily_requests | select(type == "object" and (.used | type == "number") and (.limit | type == "number") and (.remaining | type == "number")) | {used,limit,remaining}' "$response_body" 2>/dev/null || true)"
  if [[ "$REQUEST_CODE" == "200" && -n "$quota" ]]; then
    record "key_$label" VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "" '[]' null "$quota" null "" null "$key_health"
    return 0
  fi
  if [[ "$REQUEST_CODE" == "401" || "$REQUEST_CODE" == "403" ]]; then
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 invalid_key '[]' null null null "" null "$key_health"
  elif [[ "$REQUEST_CODE" == "000" || "$REQUEST_CODE" == "429" || "$REQUEST_CODE" == 5* ]]; then
    record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "openrouter_http_${REQUEST_CODE:-000}" '[]' null null null "" null "$key_health"
  elif [[ "$REQUEST_CODE" == "200" ]]; then
    record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 free_model_daily_requests_unavailable '[]' null null null "" null "$key_health"
  else
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "openrouter_http_${REQUEST_CODE:-000}" '[]' null null null "" null "$key_health"
  fi
  return 1
}

test_saved_key() {
  local label="$1" key_id raw_key saved_fingerprint raw_fingerprint key_health
  case "$label" in
    "$STAGING_PRIMARY_LABEL") raw_key="$STAGING_OPENROUTER_KEY" ;;
    "$STAGING_SECONDARY_LABEL") raw_key="$STAGING_SECONDARY_OPENROUTER_KEY" ;;
    *) record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 unknown_staging_key_label; return 1 ;;
  esac
  [[ -n "$raw_key" ]] || { record "key_$label" INCONCLUSIVE "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_raw_key; return 1; }
  request GET /api/v1/llm/provider-keys
  if [[ "$REQUEST_CODE" != "200" ]] || ! jq -e 'type == "array"' "$response_body" >/dev/null 2>&1; then
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 key_list_failed
    return 1
  fi
  key_id="$(jq -r --arg label "$label" '.[] | select(.label == $label) | .id' "$response_body" | head -n1)"
  if [[ -z "$key_id" || "$key_id" == "null" ]]; then
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 missing_saved_key
    return 1
  fi
  saved_fingerprint="$(jq -r --arg id "$key_id" '.[] | select(.id == $id) | .fingerprint' "$response_body" | head -n1)"
  raw_fingerprint="$(printf '%s' "$raw_key" | shasum -a 256 | awk '{print substr($1, 1, 12)}')"
  if [[ -z "$saved_fingerprint" || "$saved_fingerprint" != "$raw_fingerprint" ]]; then
    record "key_$label" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 saved_key_fingerprint_mismatch
    return 1
  fi
  key_health="$(jq -c --arg id "$key_id" '.[] | select(.id == $id) | {id,status,failure_count,cooldown_until,last_error,last_used_at}' "$response_body" | head -n1)"
  check_openrouter_key_account "$label" "$raw_key" "${key_health:-null}"
}

completion() {
  local check_name="${1:-completion}" message="${2:-${STAGING_COMPLETION_MESSAGE:-Analyze the valuation workflow for AAPL and return a concise result.}}"
  local run_payload run_id event_count terminal_count completed_count failed_count attempt=1 provider_started_at resume_count=0 needs_ticker_resume next_run_id resume_request snapshot_path run_status completion_request_id completion_latency_ms
  LAST_PROVIDER_CALLS='[]'
  LAST_PROVIDER_USAGE='null'
  LAST_PROVIDER_RETRY_COUNT=0
  LAST_PROVIDER_SUCCESS_COUNT=0
  LAST_PROVIDER_EVIDENCE_AVAILABLE=0
  LAST_COMPLETION_ATTEMPTS=1
  LAST_COMPLETION_REQUEST_ID=""
  LAST_COMPLETION_LATENCY_MS=0
  run_payload="$(jq -cn --arg message "$message" '{message:$message}')"
  provider_started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  while (( attempt <= RETRY_ATTEMPTS )); do
    request POST "/api/v1/threads/$THREAD_ID/runs" "$run_payload" "$CSRF_TOKEN"
    run_id="$(jq -r '.run_id // empty' "$response_body" 2>/dev/null || true)"
    if [[ "$REQUEST_CODE" == "202" ]]; then
      ACTIVE_RUN_ID="$run_id"
      ACTIVE_RUN_THREAD_ID="$THREAD_ID"
      completion_request_id="$REQUEST_ID"
      completion_latency_ms="$REQUEST_LATENCY_MS"
      record completion_start VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt"
      break
    fi
    if [[ "$REQUEST_CODE" != "429" && "$REQUEST_CODE" != "500" && "$REQUEST_CODE" != "502" && "$REQUEST_CODE" != "503" && "$REQUEST_CODE" != "504" ]]; then
      completion_request_id="$REQUEST_ID"
      completion_latency_ms="$REQUEST_LATENCY_MS"
      fail_completion "$check_name" "http_$REQUEST_CODE" "$provider_started_at" "$completion_request_id" "$completion_latency_ms" "$attempt"
      return 1
    fi
    record completion_start RETRY "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$attempt" "http_$REQUEST_CODE"
    attempt=$((attempt + 1))
    sleep "$attempt"
  done
  if [[ -z "$run_id" ]]; then
    fail_completion "$check_name" retry_exhausted "$provider_started_at" "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$RETRY_ATTEMPTS"
    return 1
  fi
  curl --silent --max-time "$TIMEOUT_SECONDS" -N \
    -H 'Accept: text/event-stream' -H "Last-Event-ID: 0" -b "$cookie_jar" \
    "$BACKEND_ORIGIN/api/v1/threads/$THREAD_ID/events?run_id=$run_id&after_seq=0" \
    | awk 'BEGIN { RS=""; ORS="\n\n" } { print; if (($0 ~ /"activity_id"[[:space:]]*:[[:space:]]*"workflow"/ && $0 ~ /"status"[[:space:]]*:[[:space:]]*"(completed|failed|cancelled)"/) || ($0 ~ /"activity_id"[[:space:]]*:[[:space:]]*"intent\.clarifying"/ && $0 ~ /"status"[[:space:]]*:[[:space:]]*"waiting"/ && $0 ~ /"interaction_id"/)) exit }' \
    >> "$sse_body" || true
  while :; do
    needs_ticker_resume="$(jq -r --arg run_id "$run_id" '
      [.active_activities[]? | select(.run_id == $run_id and .status == "waiting" and .interruption.request.type == "ticker_selection")]
      | length > 0
    ' "$response_body" 2>/dev/null || printf 'false')"
    [[ "$needs_ticker_resume" == "true" ]] || break
    if (( resume_count >= ${STAGING_MAX_RESUMES:-2} )); then
      fail_completion "$check_name" ticker_resume_limit "$provider_started_at" "$completion_request_id" "$completion_latency_ms" "$attempt"
      return 1
    fi
    snapshot_path="/api/v1/threads/$THREAD_ID/activities"
    request GET "$snapshot_path"
    run_status="$(jq -r --arg run_id "$run_id" 'if .run_id == $run_id then (.run_status // "unknown") else "superseded" end' "$response_body" 2>/dev/null || printf 'unknown')"
    if [[ "$REQUEST_CODE" != "200" || "$run_status" != "waiting" ]]; then
      fail_completion "$check_name" "ticker_run_${run_status}" "$provider_started_at" "$completion_request_id" "$completion_latency_ms" "$attempt"
      return 1
    fi
    resume_request="$(jq -ce --arg symbol "$STAGING_RESUME_TICKER" '
      [.active_activities[]? | select(.status == "waiting" and .interruption.request.type == "ticker_selection")]
      | first as $activity
      | if $activity == null then error("waiting ticker interaction is missing") else
          $activity.interruption.request.candidates as $candidates
          | {
              activity_id: $activity.activity_id,
              interaction_id: $activity.interruption.interaction_id,
              response: {
                type: "ticker_selection",
                selected_symbol: (if ($candidates | map(.symbol) | index($symbol)) == null then $candidates[0].symbol else $symbol end)
              }
            }
        end
    ' "$response_body")"
    request POST "/api/v1/threads/$THREAD_ID/runs/$run_id/resume" "$resume_request" "$CSRF_TOKEN"
    next_run_id="$(jq -r '.run_id // empty' "$response_body" 2>/dev/null || true)"
    if [[ "$REQUEST_CODE" != "202" || -z "$next_run_id" || "$next_run_id" != "$run_id" ]]; then
      completion_request_id="$REQUEST_ID"
      completion_latency_ms="$REQUEST_LATENCY_MS"
      fail_completion "$check_name" "ticker_resume_http_$REQUEST_CODE" "$provider_started_at" "$completion_request_id" "$completion_latency_ms" "$attempt"
      return 1
    fi
    resume_count=$((resume_count + 1))
    record completion_resume VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$resume_count"
    run_id="$next_run_id"
    ACTIVE_RUN_ID="$run_id"
    ACTIVE_RUN_THREAD_ID="$THREAD_ID"
    completion_request_id="$REQUEST_ID"
    completion_latency_ms="$REQUEST_LATENCY_MS"
    curl --silent --max-time "$TIMEOUT_SECONDS" -N \
      -H 'Accept: text/event-stream' -H "Last-Event-ID: 0" -b "$cookie_jar" \
      "$BACKEND_ORIGIN/api/v1/threads/$THREAD_ID/events?run_id=$run_id&after_seq=0" \
      | awk 'BEGIN { RS=""; ORS="\n\n" } { print; if ($0 ~ /"activity_id"[[:space:]]*:[[:space:]]*"workflow"/ && $0 ~ /"status"[[:space:]]*:[[:space:]]*"(completed|failed|cancelled)"/) exit }' \
      >> "$sse_body" || true
  done
  event_count="$(awk '/^event: / {count++} END {print count+0}' "$sse_body")"
  terminal_count="$(
    awk '/^data: / {sub(/^data: /, ""); print}' "$sse_body" |
      jq -s --arg run_id "$run_id" '[.[] | select(.event_name == "workflow.activity" and .run_id == $run_id and .payload.run_id == $run_id and .payload.activity_id == "workflow" and (.payload.status == "completed" or .payload.status == "failed" or .payload.status == "cancelled"))] | length'
  )"
  completed_count="$(
    awk '/^data: / {sub(/^data: /, ""); print}' "$sse_body" |
      jq -s --arg run_id "$run_id" '[.[] | select(.event_name == "workflow.activity" and .run_id == $run_id and .payload.run_id == $run_id and .payload.activity_id == "workflow" and .payload.status == "completed")] | length'
  )"
  failed_count=$((terminal_count - completed_count))
  if (( terminal_count > 0 )); then
    ACTIVE_RUN_ID=""
    ACTIVE_RUN_THREAD_ID=""
  else
    cancel_active_run || true
  fi
  capture_completion_evidence "$provider_started_at" "$completion_request_id" "$completion_latency_ms" "$attempt"
  if (( event_count > 0 && completed_count > 0 && failed_count == 0 && LAST_PROVIDER_SUCCESS_COUNT > 0 )); then
    record "$check_name" VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
  else
    local failure_code="no_terminal_event"
    (( failed_count > 0 )) && failure_code="workflow_failed"
    (( completed_count > 0 && LAST_PROVIDER_SUCCESS_COUNT == 0 )) && failure_code="no_successful_provider_call"
    record "$check_name" NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "$failure_code" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    return 1
  fi
}

failover_probe() {
  if [[ -z "$PRIMARY_KEY_ID" || -z "$SECONDARY_KEY_ID" || "$PRIMARY_KEY_ID" == "$SECONDARY_KEY_ID" ]]; then
    record failover INCONCLUSIVE "" 0 1 missing_distinct_key_pool
    return 1
  fi
  if [[ -z "$STAGING_OPENROUTER_KEY" ]]; then
    record failover INCONCLUSIVE "" 0 1 missing_primary_raw_key
    return 1
  fi
  if [[ -n "$ACTIVE_RUN_ID" ]]; then
    record failover INCONCLUSIVE "" 0 1 active_run_cleanup_incomplete
    return 1
  fi

  THREAD_ID="${BASE_THREAD_ID}-failover"

  request DELETE "/api/v1/llm/provider-keys/$PRIMARY_KEY_ID" "" "$CSRF_TOKEN"
  if [[ "$REQUEST_CODE" != "204" ]]; then
    record failover NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
    return 1
  fi
  PRIMARY_DELETED=1
  record failover_injection VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"

  if completion failover_completion "Fail over to the secondary provider key and analyze the valuation workflow for AAPL."; then
    local secondary_calls
    secondary_calls="$(jq -r --arg fingerprint "$SECONDARY_KEY_FINGERPRINT" --arg key_id "$SECONDARY_KEY_ID" '[.[] | select((.key_fingerprint == $fingerprint or .deployment_id == $key_id) and .error_code == null)] | length' <<< "$LAST_PROVIDER_CALLS")"
    if (( secondary_calls > 0 )); then
      record failover VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    else
      record failover NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" secondary_deployment_not_observed "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
      return 1
    fi
  else
    record failover NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 no_real_provider_completion "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    return 1
  fi
  restore_primary_key
}

provider_failover_probe() {
  if [[ -z "$PRIMARY_KEY_ID" || -z "$SECONDARY_KEY_ID" || "$PRIMARY_KEY_ID" == "$SECONDARY_KEY_ID" ]]; then
    record failover INCONCLUSIVE "" 0 1 missing_distinct_key_pool
    return 1
  fi
  if [[ -z "$LLM_PROVIDER_SERVICE_TOKEN" ]]; then
    record failover INCONCLUSIVE "" 0 1 missing_provider_service_token
    return 1
  fi

  THREAD_ID="${BASE_THREAD_ID}-failover"
  request DELETE "/api/v1/llm/provider-keys/$PRIMARY_KEY_ID" "" "$CSRF_TOKEN"
  if [[ "$REQUEST_CODE" != "204" ]]; then
    record failover NOT_VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS" 1 "http_$REQUEST_CODE"
    return 1
  fi
  PRIMARY_DELETED=1
  record failover_injection VERIFIED "$REQUEST_ID" "$REQUEST_LATENCY_MS"

  if provider_completion failover_completion; then
    if [[ "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" == "$SECONDARY_KEY_FINGERPRINT" || "$LAST_COMPLETION_ATTRIBUTION_DEPLOYMENT_ID" == "$SECONDARY_KEY_ID" ]]; then
      record failover VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE" null 200 "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" "$LAST_PROVIDER_RESULT_EVIDENCE"
    else
      record failover NOT_VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" secondary_deployment_not_observed "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE" null 200 "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" "$LAST_PROVIDER_RESULT_EVIDENCE"
      return 1
    fi
  else
    record failover NOT_VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" no_real_provider_completion "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    return 1
  fi
  restore_primary_key
}

if ! health_check; then
  echo "Staging smoke health check failed; report: $REPORT" >&2
  exit 1
fi

if ! secret_bundle_available; then
  record live_provider INCONCLUSIVE "" 0 1 missing_secret_bundle
  record retry INCONCLUSIVE "" 0 1 missing_secret_bundle
  record failover INCONCLUSIVE "" 0 1 missing_secret_bundle
  echo "Staging smoke recorded health and an inconclusive live-provider gate; no secret bundle was available. Report: $REPORT"
  exit 0
fi

login
if [[ "$SMOKE_MODE" == "restore-only" ]]; then
  PRIMARY_DELETED=1
  if restore_primary_key; then
    echo "Staging primary-key restoration verified; report: $REPORT"
    exit 0
  fi
  echo "Staging primary-key restoration failed; report: $REPORT" >&2
  exit 1
fi

if [[ "$SMOKE_MODE" == "keys-only" ]]; then
  test_saved_key "$STAGING_PRIMARY_LABEL" || SMOKE_FAILED=1
  sleep "${STAGING_KEY_TEST_DELAY_SECONDS:-2}"
  test_saved_key "$STAGING_SECONDARY_LABEL" || SMOKE_FAILED=1
  echo "Staging key-only smoke completed; report: $REPORT"
  exit "$SMOKE_FAILED"
fi

if ensure_key "$STAGING_PRIMARY_LABEL" "$STAGING_OPENROUTER_KEY"; then
  PRIMARY_KEY_ID="$ENSURED_KEY_ID"
  PRIMARY_KEY_FINGERPRINT="$ENSURED_KEY_FINGERPRINT"
  if [[ -n "$PRIMARY_KEY_ID" ]]; then
    PRIMARY_KEY_READY=1
  else
    SMOKE_FAILED=1
  fi
else
  SMOKE_FAILED=1
fi
if ensure_key "$STAGING_SECONDARY_LABEL" "$STAGING_SECONDARY_OPENROUTER_KEY"; then
  SECONDARY_KEY_ID="$ENSURED_KEY_ID"
  SECONDARY_KEY_FINGERPRINT="$ENSURED_KEY_FINGERPRINT"
  if [[ -n "$SECONDARY_KEY_ID" ]]; then
    SECONDARY_KEY_READY=1
  else
    SMOKE_FAILED=1
  fi
else
  SMOKE_FAILED=1
fi
select_completion_model
if [[ "$SMOKE_MODE" == "provider-probe" ]]; then
  if [[ "$PRIMARY_KEY_READY" != "1" || "$SECONDARY_KEY_READY" != "1" ]]; then
    record live_provider INCONCLUSIVE "" 0 1 missing_verified_key_pair
    record retry INCONCLUSIVE "" 0 1 missing_verified_key_pair
    record failover INCONCLUSIVE "" 0 1 missing_verified_key_pair
    SMOKE_FAILED=1
  elif [[ -z "$LLM_PROVIDER_SERVICE_TOKEN" ]]; then
    record live_provider INCONCLUSIVE "" 0 1 missing_provider_service_token
    record retry INCONCLUSIVE "" 0 1 missing_provider_service_token
    record failover INCONCLUSIVE "" 0 1 missing_provider_service_token
    SMOKE_FAILED=1
  else
    retry_recorded=0
    if provider_completion completion; then
      record live_provider VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE" null 200 "$LAST_COMPLETION_ATTRIBUTION_FINGERPRINT" "$LAST_PROVIDER_RESULT_EVIDENCE"
    else
      record live_provider NOT_VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" completion_not_verified "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
      SMOKE_FAILED=1
    fi
    if (( LAST_PROVIDER_RETRY_COUNT > 0 )); then
      record retry VERIFIED "$LAST_PROVIDER_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
      retry_recorded=1
    fi
    provider_failover_probe || SMOKE_FAILED=1
    if (( retry_recorded == 0 )); then
      if (( LAST_PROVIDER_RETRY_COUNT > 0 )); then
        record retry VERIFIED "$LAST_PROVIDER_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
      else
        record retry INCONCLUSIVE "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" no_provider_retry_observed "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
        SMOKE_FAILED=1
      fi
    fi
  fi
  echo "Staging provider probe completed; report: $REPORT"
  exit "$SMOKE_FAILED"
fi
if [[ "$PRIMARY_KEY_READY" == "1" ]]; then
  if completion; then
    record live_provider VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
  else
    local_live_code="completion_not_verified"
    (( LAST_PROVIDER_EVIDENCE_AVAILABLE == 0 )) && local_live_code="provider_telemetry_unavailable"
    record live_provider NOT_VERIFIED "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "$local_live_code" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    SMOKE_FAILED=1
  fi
  if (( LAST_PROVIDER_EVIDENCE_AVAILABLE == 1 && LAST_PROVIDER_RETRY_COUNT > 0 )); then
    record retry VERIFIED "$LAST_PROVIDER_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" "" "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
  elif (( LAST_PROVIDER_EVIDENCE_AVAILABLE == 1 )); then
    record retry INCONCLUSIVE "$LAST_PROVIDER_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" no_provider_retry_observed "$LAST_PROVIDER_CALLS" "$LAST_PROVIDER_USAGE"
    SMOKE_FAILED=1
  else
    record retry INCONCLUSIVE "$LAST_COMPLETION_REQUEST_ID" "$LAST_COMPLETION_LATENCY_MS" "$LAST_COMPLETION_ATTEMPTS" provider_telemetry_unavailable
    SMOKE_FAILED=1
  fi
else
  record live_provider INCONCLUSIVE "" 0 1 missing_primary_key
  record retry INCONCLUSIVE "" 0 1 missing_primary_key
  SMOKE_FAILED=1
fi

if [[ "$PRIMARY_KEY_READY" == "1" && "$SECONDARY_KEY_READY" == "1" ]]; then
  if ! failover_probe; then
    SMOKE_FAILED=1
  fi
else
  record failover INCONCLUSIVE "" 0 1 missing_verified_key_pair
  SMOKE_FAILED=1
fi

echo "Staging smoke completed; report: $REPORT"
exit "$SMOKE_FAILED"
