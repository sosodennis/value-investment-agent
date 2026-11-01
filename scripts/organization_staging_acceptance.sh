#!/usr/bin/env bash
set -euo pipefail

# Fresh-staging collaboration acceptance. This script records only safe status
# metadata; credentials, cookies, provider keys, and email addresses stay local.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SECRET_FILE="${STAGING_SECRET_FILE:-$ROOT/.env.staging}"
REPORT="${STAGING_ORGANIZATION_REPORT:-/tmp/value-investment-agent-216-organization.jsonl}"
FIXTURE_FILE="${STAGING_BOB_FIXTURE:-/tmp/value-investment-agent-216-bob.env}"
PROJECT="${COMPOSE_PROJECT_NAME:-value-investment-agent-216-staging}"
RUN_ID="${STAGING_ACCEPTANCE_RUN_ID:-$(date -u +%Y%m%d%H%M%S)-$$}"

for command in curl jq awk date sleep docker; do
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

BACKEND_ORIGIN="$(read_secret STAGING_BASE_URL || true)"
BACKEND_ORIGIN="${BACKEND_ORIGIN:-http://127.0.0.1:$(read_secret BACKEND_HOST_PORT || printf '8000')}"
BACKEND_ORIGIN="${BACKEND_ORIGIN%/}"
STAGING_PASSWORD="$(read_secret STAGING_PASSWORD || true)"
STAGING_ACCEPTANCE_PASSWORD="$(read_secret STAGING_ACCEPTANCE_PASSWORD || true)"
STAGING_ACCEPTANCE_PASSWORD="${STAGING_ACCEPTANCE_PASSWORD:-$STAGING_PASSWORD}"
STAGING_ACCEPTANCE_EMAIL_DOMAIN="$(read_secret STAGING_ACCEPTANCE_EMAIL_DOMAIN || true)"
STAGING_ACCEPTANCE_EMAIL_DOMAIN="${STAGING_ACCEPTANCE_EMAIL_DOMAIN:-staging.invalid}"
STAGING_ACCEPTANCE_EMAIL_PREFIX="$(read_secret STAGING_ACCEPTANCE_EMAIL_PREFIX || true)"
STAGING_ACCEPTANCE_EMAIL_PREFIX="${STAGING_ACCEPTANCE_EMAIL_PREFIX:-org-acceptance-${RUN_ID}}"
STAGING_KEY_IMPORT_FILE="${STAGING_KEY_IMPORT_FILE:-}"

[[ -n "$STAGING_ACCEPTANCE_PASSWORD" ]] || {
  echo "STAGING_ACCEPTANCE_PASSWORD or STAGING_PASSWORD is required" >&2
  exit 2
}

mkdir -p "$(dirname "$REPORT")"
cookie_dir="$(mktemp -d)"
body_file="$(mktemp)"
headers_file="$(mktemp)"
trap 'rm -rf "$cookie_dir" "$body_file" "$headers_file"' EXIT
umask 077
: > "$REPORT"

REQUEST_CODE=""
REQUEST_ID=""
REQUEST_LATENCY_MS=0

record() {
  local check="$1" status="$2" code="${3:-0}" detail="${4:-}"
  jq -cn \
    --arg check "$check" --arg status "$status" --arg code "$code" \
    --arg detail "$detail" --arg run_id "$RUN_ID" \
    '{check:$check,status:$status,http_code:($code|tonumber),detail:$detail,run_id:$run_id}' \
    >> "$REPORT"
}

fail() {
  local check="$1" detail="$2"
  record "$check" NOT_VERIFIED "${REQUEST_CODE:-0}" "$detail"
  echo "organization staging acceptance failed at $check: $detail; report: $REPORT" >&2
  exit 1
}

jar_for() {
  printf '%s/%s.cookies' "$cookie_dir" "$1"
}

csrf_for() {
  awk '$6 == "app_csrf" {print $7; exit}' "$(jar_for "$1")"
}

request() {
  local user="$1" method="$2" path="$3" payload="${4:-}" csrf="${5:-}" org_header="${6:-}" idempotency="${7:-}"
  local started ended code
  touch "$(jar_for "$user")"
  started="$(date +%s)"
  local -a args=(curl --silent --show-error --max-time 60 --output "$body_file" --dump-header "$headers_file" --write-out '%{http_code}' -X "$method" "$BACKEND_ORIGIN$path" -b "$(jar_for "$user")" -c "$(jar_for "$user")" -H 'Accept: application/json')
  [[ -n "$payload" ]] && args+=( -H 'Content-Type: application/json' --data "$payload" )
  [[ -n "$csrf" ]] && args+=( -H "X-CSRF-Token: $csrf" )
  [[ -n "$org_header" ]] && args+=( -H "X-Organization-ID: $org_header" )
  [[ -n "$idempotency" ]] && args+=( -H "Idempotency-Key: $idempotency" )
  code="$("${args[@]}" 2>/dev/null || true)"
  ended="$(date +%s)"
  REQUEST_CODE="$code"
  REQUEST_LATENCY_MS=$(((ended - started) * 1000))
  REQUEST_ID="$(awk 'BEGIN{IGNORECASE=1} /^x-request-id:/ {gsub("\r", "", $2); print $2; exit}' "$headers_file")"
}

request_file() {
  local user="$1" method="$2" path="$3" file="$4" csrf="${5:-}" idempotency="${6:-}"
  local code
  touch "$(jar_for "$user")"
  local -a args=(curl --silent --show-error --max-time 120 --output "$body_file" --dump-header "$headers_file" --write-out '%{http_code}' -X "$method" "$BACKEND_ORIGIN$path" -b "$(jar_for "$user")" -c "$(jar_for "$user")" -H 'Accept: application/json' -F "file=@$file")
  [[ -n "$csrf" ]] && args+=( -H "X-CSRF-Token: $csrf" )
  [[ -n "$idempotency" ]] && args+=( -H "Idempotency-Key: $idempotency" )
  code="$("${args[@]}" 2>/dev/null || true)"
  REQUEST_CODE="$code"
  REQUEST_ID="$(awk 'BEGIN{IGNORECASE=1} /^x-request-id:/ {gsub("\r", "", $2); print $2; exit}' "$headers_file")"
}

expect_code() {
  local check="$1" expected="$2" detail="${3:-}"
  if [[ "$REQUEST_CODE" != "$expected" ]]; then
    fail "$check" "expected_http_${expected}_got_${REQUEST_CODE}_${detail}"
  fi
  record "$check" VERIFIED "$REQUEST_CODE" "$detail"
}

expect_one_of() {
  local check="$1" detail="$2"
  shift 2
  for expected in "$@"; do
    [[ "$REQUEST_CODE" == "$expected" ]] && {
      record "$check" VERIFIED "$REQUEST_CODE" "$detail"
      return 0
    }
  done
  fail "$check" "unexpected_http_${REQUEST_CODE}_${detail}"
}

json_value() {
  jq -r "$1" "$body_file"
}

register_user() {
  local user="$1" display_name="$2" email user_upper
  email="${STAGING_ACCEPTANCE_EMAIL_PREFIX}-${user}@${STAGING_ACCEPTANCE_EMAIL_DOMAIN}"
  user_upper="$(printf '%s' "$user" | tr '[:lower:]' '[:upper:]')"
  local payload
  payload="$(jq -cn --arg email "$email" --arg display_name "$display_name" --arg password "$STAGING_ACCEPTANCE_PASSWORD" '{email:$email,display_name:$display_name,password:$password}')"
  request "$user" POST /api/v1/auth/register "$payload"
  expect_code "${user}_register" 201
  printf -v "${user_upper}_ID" '%s' "$(json_value '.user_id')"
  printf -v "${user_upper}_DEFAULT_ORG" '%s' "$(json_value '.organization_id')"
  printf -v "${user_upper}_EMAIL" '%s' "$email"
  request "$user" POST /api/v1/auth/login "$(jq -cn --arg email "$email" --arg password "$STAGING_ACCEPTANCE_PASSWORD" '{email:$email,password:$password}')"
  expect_code "${user}_login" 200
}

select_org() {
  local user="$1" organization_id="$2"
  request "$user" PUT /api/v1/auth/session/organization "$(jq -cn --arg organization_id "$organization_id" '{organization_id:$organization_id}')" "$(csrf_for "$user")"
  expect_code "${user}_select_${organization_id}" 200
}

create_org() {
  local user="$1" name="$2" variable="$3"
  request "$user" POST /api/v1/organizations "$(jq -cn --arg name "$name" '{name:$name}')" "$(csrf_for "$user")"
  expect_code "${user}_create_${variable}" 201
  printf -v "$variable" '%s' "$(json_value '.organization_id')"
}

invite() {
  local user="$1" organization_id="$2" recipient_id="$3" role="$4" variable="$5" idem="$6"
  request "$user" POST "/api/v1/organizations/$organization_id/invitations" "$(jq -cn --arg recipient_user_id "$recipient_id" --arg role "$role" '{recipient_user_id:$recipient_user_id,role:$role}')" "$(csrf_for "$user")" "" "$idem"
  expect_code "${user}_invite_${variable}" 201
  printf -v "$variable" '%s' "$(json_value '.invitation_id')"
}

wait_for_notification() {
  local user="$1" invitation_id="$2" variable="$3" found="" attempts=0
  while (( attempts < 30 )); do
    request "$user" GET /api/v1/notifications
    [[ "$REQUEST_CODE" == "200" ]] || fail "${user}_notification_read" "http_${REQUEST_CODE}"
    found="$(jq -r --arg invitation_id "$invitation_id" '.items[]? | select(.action.action_ref == $invitation_id) | .notification_id' "$body_file" | head -n1)"
    [[ -n "$found" ]] && break
    attempts=$((attempts + 1))
    sleep 1
  done
  [[ -n "$found" ]] || fail "${user}_notification_delivery" "invitation_not_delivered"
  record "${user}_notification_delivery" VERIFIED 200 "recipient_private_inbox"
  printf -v "$variable" '%s' "$found"
}

invitation_action() {
  local user="$1" organization_id="$2" invitation_id="$3" operation="$4" check="$5" idem="$6"
  request "$user" POST "/api/v1/organizations/$organization_id/invitations/$invitation_id/$operation" "" "$(csrf_for "$user")" "" "$idem"
  expect_code "$check" 200
}

echo "organization staging acceptance run $RUN_ID"
register_user alice Alice
register_user bob Bob
register_user carol Carol
register_user dave Dave

create_org alice "Alpha $RUN_ID" ALPHA_ID
select_org alice "$ALPHA_ID"
create_org carol "Beta $RUN_ID" BETA_ID
select_org carol "$BETA_ID"
record organization_context VERIFIED 200 "alpha_and_beta_active_contexts_created"

request alice GET "/api/v1/organizations/$ALPHA_ID/directory/users?q=Bob&limit=20"
expect_code directory_search 200
[[ "$(jq -r --arg id "$BOB_ID" '[.items[] | select(.user_id == $id)] | length' "$body_file")" == "1" ]] || fail directory_search "bob_missing_from_directory"
record directory_search_result VERIFIED 200 "registered_non_member_found"

request alice GET "/api/v1/organizations/$ALPHA_ID/members"
expect_code alpha_initial_members 200
[[ "$(jq 'length' "$body_file")" == "1" ]] || fail alpha_initial_members "unexpected_member_count"

invite alice "$ALPHA_ID" "$BOB_ID" member INV_BOB "invite-bob-$RUN_ID"
wait_for_notification bob "$INV_BOB" BOB_NOTIFICATION
request carol GET /api/v1/notifications
expect_code carol_private_inbox 200
[[ "$(jq -r --arg id "$INV_BOB" '[.items[]? | select(.action.action_ref == $id)] | length' "$body_file")" == "0" ]] || fail carol_private_inbox "cross_recipient_notification_visible"
request carol GET "/api/v1/organizations/$ALPHA_ID/invitations/$INV_BOB"
expect_code wrong_recipient_invitation 404

invitation_action bob "$ALPHA_ID" "$INV_BOB" accept bob_accept "accept-bob-$RUN_ID"
invitation_action bob "$ALPHA_ID" "$INV_BOB" accept bob_accept_repeat "accept-bob-$RUN_ID"
select_org bob "$ALPHA_ID"
request alice GET "/api/v1/organizations/$ALPHA_ID/members"
expect_code alpha_after_bob 200
[[ "$(jq '[.[] | select(.status == "active")] | length' "$body_file")" == "2" ]] || fail alpha_after_bob "alpha_member_count_not_two"
record alpha_after_bob VERIFIED 200 "alice_and_bob_active"

invite alice "$ALPHA_ID" "$CAROL_ID" member INV_DECLINE "invite-decline-$RUN_ID"
wait_for_notification carol "$INV_DECLINE" CAROL_DECLINE_NOTIFICATION
invitation_action carol "$ALPHA_ID" "$INV_DECLINE" decline carol_decline "decline-carol-$RUN_ID"
invitation_action carol "$ALPHA_ID" "$INV_DECLINE" decline carol_decline_repeat "decline-carol-$RUN_ID"

invite alice "$ALPHA_ID" "$CAROL_ID" member INV_EXPIRE "invite-expire-$RUN_ID"
[[ "$INV_EXPIRE" =~ ^[0-9a-fA-F-]{36}$ ]] || fail invitation_expiry_setup "invalid_invitation_id"
docker compose --env-file "$SECRET_FILE" -p "$PROJECT" exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -v ON_ERROR_STOP=1 -c \"UPDATE auth_invitations SET expires_at=NOW() - INTERVAL '1 minute' WHERE id = '$INV_EXPIRE'\"" >/dev/null
request carol POST "/api/v1/organizations/$ALPHA_ID/invitations/$INV_EXPIRE/accept" "" "$(csrf_for carol)" "" "accept-expired-$RUN_ID"
if [[ "$REQUEST_CODE" != "409" ]]; then fail carol_expired_accept "expected_http_409_got_${REQUEST_CODE}"; fi
record carol_expired_accept VERIFIED "$REQUEST_CODE" "expired_invitation_rejected"

invite alice "$ALPHA_ID" "$DAVE_ID" member INV_REVOKE "invite-revoke-$RUN_ID"
wait_for_notification dave "$INV_REVOKE" DAVE_REVOKE_NOTIFICATION
invitation_action dave "$ALPHA_ID" "$INV_REVOKE" decline dave_decline_for_resend "decline-revoke-$RUN_ID"
request alice POST "/api/v1/organizations/$ALPHA_ID/invitations/$INV_REVOKE/resend" "" "$(csrf_for alice)" "" "resend-$RUN_ID"
expect_code invitation_resend 200
request alice POST "/api/v1/organizations/$ALPHA_ID/invitations/$INV_REVOKE/revoke" "" "$(csrf_for alice)" "" "revoke-$RUN_ID"
expect_code invitation_revoke 200
request dave POST "/api/v1/organizations/$ALPHA_ID/invitations/$INV_REVOKE/accept" "" "$(csrf_for dave)" "" "accept-revoked-$RUN_ID"
if [[ "$REQUEST_CODE" != "409" ]]; then fail dave_revoked_accept "expected_http_409_got_${REQUEST_CODE}"; fi
record dave_revoked_accept VERIFIED "$REQUEST_CODE" "revoked_invitation_rejected"

invite alice "$ALPHA_ID" "$DAVE_ID" member INV_REMOVE "invite-remove-$RUN_ID"
wait_for_notification dave "$INV_REMOVE" DAVE_REMOVE_NOTIFICATION
invitation_action dave "$ALPHA_ID" "$INV_REMOVE" accept dave_accept_for_removal "accept-dave-$RUN_ID"
select_org dave "$ALPHA_ID"
request alice PATCH "/api/v1/organizations/$ALPHA_ID/members/$DAVE_ID/status" '{"status":"removed"}' "$(csrf_for alice)"
expect_code dave_membership_removed 200
request dave GET /api/v1/llm/provider-keys
expect_one_of dave_revoked_provider_access "removed_membership_denied" 401 403 404
request bob PUT /api/v1/llm/settings '{"selected_model":"openrouter/free"}' "$(csrf_for bob)"
expect_one_of bob_member_llm_mutation_denied "member_cannot_mutate_provider" 403 404
request alice POST "/api/v1/organizations/$ALPHA_ID/ownership/transfer" "$(jq -cn --arg target_user_id "$BOB_ID" '{target_user_id:$target_user_id}')" "$(csrf_for alice)"
expect_code ownership_transfer 200
request bob PATCH "/api/v1/organizations/$ALPHA_ID/members/$ALICE_ID/role" '{"role":"admin"}' "$(csrf_for bob)"
expect_code promote_admin_for_owner_guard 200
request alice PATCH "/api/v1/organizations/$ALPHA_ID/members/$BOB_ID/status" '{"status":"removed"}' "$(csrf_for alice)"
expect_code last_owner_protection 403
[[ "$(json_value '.detail')" == "last_owner_protected" ]] || fail last_owner_protection "unexpected_detail_$(json_value '.detail')"

if [[ -n "$STAGING_KEY_IMPORT_FILE" ]]; then
  request_file alice POST /api/v1/llm/provider-keys/imports "$STAGING_KEY_IMPORT_FILE" "$(csrf_for alice)" "alpha-import-$RUN_ID"
  expect_code alpha_llm_import 202
  batch_id="$(json_value '.id')"
  attempts=0
  while (( attempts < 60 )); do
    request alice GET "/api/v1/llm/provider-keys/imports/$batch_id"
    [[ "$REQUEST_CODE" == "200" ]] || fail alpha_llm_import_poll "http_${REQUEST_CODE}"
    import_status="$(json_value '.status')"
    [[ "$import_status" == completed || "$import_status" == completed_with_errors ]] && break
    attempts=$((attempts + 1))
    sleep 2
  done
  [[ "$import_status" == completed || "$import_status" == completed_with_errors ]] || fail alpha_llm_import "import_timeout"
  [[ "$(json_value '.invalid_count')" == "0" && "$(json_value '.retryable_count')" == "0" ]] || fail alpha_llm_import "invalid_or_retryable_rows"
  record alpha_llm_import VERIFIED 200 "batch_${import_status}"
fi

request alice GET /api/v1/llm/settings
expect_code alpha_llm_settings 200
request bob GET /api/v1/llm/settings
expect_code bob_shared_llm_settings 200
request bob GET /api/v1/llm/provider-keys
expect_code bob_shared_llm_keys 200

request alice GET /api/v1/search/settings "" "" "$ALPHA_ID"
expect_code alpha_search_settings 200
request alice PUT /api/v1/search/settings '{"providers":[{"provider":"ddgs","enabled":true,"priority":0},{"provider":"tavily","enabled":false,"priority":1}]}' "$(csrf_for alice)" "$ALPHA_ID"
expect_code alpha_search_settings_update 200
request bob GET /api/v1/search/settings "" "" "$ALPHA_ID"
expect_code bob_shared_search_settings 200
request carol GET /api/v1/search/settings "" "" "$ALPHA_ID"
expect_one_of carol_cross_org_search_denied "beta_context_cannot_read_alpha" 403 404 409
request carol GET /api/v1/search/settings "" "" "$BETA_ID"
expect_code carol_beta_search_settings 200

request alice GET "/api/v1/organizations/$ALPHA_ID/audit-events?limit=100"
expect_code alpha_audit_read 200
request carol GET "/api/v1/organizations/$ALPHA_ID/audit-events?limit=100"
expect_one_of carol_cross_org_audit_denied "cross_org_audit_denied" 403 404

printf 'STAGING_EMAIL=%s\nSTAGING_PASSWORD=%s\nSTAGING_DISPLAY_NAME=Bob\nSTAGING_ORGANIZATION_ID=%s\n' "$BOB_EMAIL" "$STAGING_ACCEPTANCE_PASSWORD" "$ALPHA_ID" > "$FIXTURE_FILE"
chmod 600 "$FIXTURE_FILE"
record bob_runtime_fixture VERIFIED 200 "fixture_path_local_only"
echo "Organization staging acceptance completed; report: $REPORT; Bob fixture: $FIXTURE_FILE"
