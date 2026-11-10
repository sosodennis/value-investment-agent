#!/usr/bin/env bash

# Validate the exact Git, Compose, and HTTP runtime tuple used for acceptance.
# Values printed by this script are paths, identifiers, URLs, and ports only.

set -euo pipefail

fail() {
  printf 'acceptance preflight: FAIL: %s\n' "$*" >&2
  exit 1
}

require_value() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "set ${name}"
}

require_file() {
  local name="$1"
  local value="${!name:-}"
  [[ "$value" == "none" || -f "$value" ]] || fail "${name} does not name a file: ${value}"
}

ACCEPTANCE_MANIFEST="${ACCEPTANCE_MANIFEST:-}"
if [[ -n "$ACCEPTANCE_MANIFEST" ]]; then
  command -v python3 >/dev/null 2>&1 || fail "python3 is unavailable for ACCEPTANCE_MANIFEST"
  manifest_validator="${ACCEPTANCE_MANIFEST_VALIDATOR:-scripts/validate_acceptance_manifest.py}"
  [[ -f "$manifest_validator" ]] || fail "manifest validator does not exist: ${manifest_validator}"
  if ! manifest_env="$(python3 "$manifest_validator" --path "$ACCEPTANCE_MANIFEST" --emit-preflight-env)"; then
    fail "acceptance manifest validation failed: ${ACCEPTANCE_MANIFEST}"
  fi
  while IFS=$'\t' read -r key value; do
    [[ -n "$key" ]] || continue
    case "$key" in
      EXPECTED_WORKTREE|EXPECTED_BRANCH|EXPECTED_COMMIT|APP_COMPOSE_PROJECT|APP_COMPOSE_FILES|APP_ENV_FILE|APP_URL|APP_EXPECTED_PORT|APP_SERVICE|APP_CONTAINER_PORT|FUNDAMENTAL_COMPOSE_PROJECT|FUNDAMENTAL_COMPOSE_FILES|FUNDAMENTAL_ENV_FILE|FUNDAMENTAL_URL|FUNDAMENTAL_EXPECTED_PORT|FUNDAMENTAL_SERVICE|FUNDAMENTAL_CONTAINER_PORT|REQUIRE_SEC_IDENTITY_RESOLUTION|ALLOWED_UNTRACKED_PATHS)
        printf -v "$key" '%s' "$value"
        ;;
      *)
        fail "manifest emitted an unsupported preflight variable: ${key}"
        ;;
    esac
  done <<< "$manifest_env"
fi

for required in \
  EXPECTED_WORKTREE \
  EXPECTED_BRANCH \
  EXPECTED_COMMIT \
  APP_COMPOSE_PROJECT \
  APP_COMPOSE_FILES \
  APP_ENV_FILE \
  APP_URL \
  APP_EXPECTED_PORT \
  FUNDAMENTAL_COMPOSE_PROJECT \
  FUNDAMENTAL_COMPOSE_FILES \
  FUNDAMENTAL_ENV_FILE \
  FUNDAMENTAL_URL \
  FUNDAMENTAL_EXPECTED_PORT; do
  require_value "$required"
done

REQUIRE_EXACT_COMMIT="${REQUIRE_EXACT_COMMIT:-1}"
REQUIRE_SEC_IDENTITY_RESOLUTION="${REQUIRE_SEC_IDENTITY_RESOLUTION:-0}"
ALLOWED_UNTRACKED_PATHS="${ALLOWED_UNTRACKED_PATHS:-}"
START_ACCEPTANCE_STACK="${START_ACCEPTANCE_STACK:-0}"
ACCEPTANCE_BUILD="${ACCEPTANCE_BUILD:-0}"
APP_SERVICE="${APP_SERVICE:-backend}"
APP_CONTAINER_PORT="${APP_CONTAINER_PORT:-8000}"
FUNDAMENTAL_SERVICE="${FUNDAMENTAL_SERVICE:-fundamental-service}"
FUNDAMENTAL_CONTAINER_PORT="${FUNDAMENTAL_CONTAINER_PORT:-8080}"

case "$REQUIRE_EXACT_COMMIT" in
  0|1) ;;
  *) fail "REQUIRE_EXACT_COMMIT must be 0 or 1" ;;
esac
case "$REQUIRE_SEC_IDENTITY_RESOLUTION" in
  0|1) ;;
  *) fail "REQUIRE_SEC_IDENTITY_RESOLUTION must be 0 or 1" ;;
esac
case "$START_ACCEPTANCE_STACK" in
  0|1) ;;
  *) fail "START_ACCEPTANCE_STACK must be 0 or 1" ;;
esac
case "$ACCEPTANCE_BUILD" in
  0|1) ;;
  *) fail "ACCEPTANCE_BUILD must be 0 or 1" ;;
esac

command -v git >/dev/null 2>&1 || fail "git is unavailable"
command -v docker >/dev/null 2>&1 || fail "docker is unavailable"
command -v curl >/dev/null 2>&1 || fail "curl is unavailable"
command -v python3 >/dev/null 2>&1 || fail "python3 is unavailable"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "run inside a Git worktree"
expected_root="$(cd "$EXPECTED_WORKTREE" 2>/dev/null && pwd -P)" || fail "EXPECTED_WORKTREE does not exist: ${EXPECTED_WORKTREE}"
current_dir="$(pwd -P)"
[[ "$repo_root" == "$expected_root" ]] || fail "Git worktree is ${repo_root}, expected ${expected_root}"
[[ "$current_dir" == "$expected_root" ]] || fail "run from worktree root ${expected_root}, current directory is ${current_dir}"

branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null)" || fail "worktree is detached"
[[ "$branch" == "$EXPECTED_BRANCH" ]] || fail "branch is ${branch}, expected ${EXPECTED_BRANCH}"

head="$(git rev-parse HEAD 2>/dev/null)" || fail "cannot resolve HEAD"
if [[ "$REQUIRE_EXACT_COMMIT" == 1 ]]; then
  [[ "$head" == "$EXPECTED_COMMIT" ]] || fail "HEAD is ${head}, expected ${EXPECTED_COMMIT}"
  git diff --quiet || fail "worktree has unstaged tracked changes"
  git diff --cached --quiet || fail "worktree has staged tracked changes"
  status_lines="$(git status --porcelain=v1 --untracked-files=all)"
  if [[ -n "$status_lines" ]]; then
    while IFS= read -r status_line; do
      [[ -n "$status_line" ]] || continue
      if [[ "$status_line" != "?? "* ]]; then
        fail "worktree has tracked status changes: ${status_line}"
      fi
      path="${status_line#?? }"
      allowed=false
      IFS=':' read -r -a allowed_paths <<< "$ALLOWED_UNTRACKED_PATHS"
      for allowed_path in "${allowed_paths[@]}"; do
        if [[ -n "$allowed_path" && "$path" == "$allowed_path" ]]; then
          allowed=true
          break
        fi
      done
      [[ "$allowed" == true ]] || fail "untracked path is not explicitly allowed: ${path}"
    done <<< "$status_lines"
  fi
fi

require_file APP_ENV_FILE
require_file FUNDAMENTAL_ENV_FILE

compose() {
  local project="$1"
  local env_file="$2"
  local files="$3"
  shift 3

  local -a command=(docker compose)
  if [[ "$env_file" != "none" ]]; then
    command+=(--env-file "$env_file")
  fi
  command+=(-p "$project")

  local -a file_list=()
  IFS=':' read -r -a file_list <<< "$files"
  local compose_file
  for compose_file in "${file_list[@]}"; do
    [[ -n "$compose_file" ]] || fail "empty Compose file in ${project} file list"
    [[ -f "$compose_file" ]] || fail "Compose file does not exist: ${compose_file}"
    command+=(-f "$compose_file")
  done
  "${command[@]}" "$@"
}

if ! compose "$APP_COMPOSE_PROJECT" "$APP_ENV_FILE" "$APP_COMPOSE_FILES" config --quiet >/dev/null 2>&1; then
  fail "application Compose configuration is invalid"
fi
if ! compose "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_ENV_FILE" "$FUNDAMENTAL_COMPOSE_FILES" config --quiet >/dev/null 2>&1; then
  fail "Fundamental Compose configuration is invalid"
fi

if [[ "$REQUIRE_SEC_IDENTITY_RESOLUTION" == 1 ]]; then
  [[ "$FUNDAMENTAL_COMPOSE_FILES" == *"docker-compose.issue312-sec-ingestion.yml"* ]] || \
    fail "SEC-backed acceptance must include docker-compose.issue312-sec-ingestion.yml"
fi

if [[ "$START_ACCEPTANCE_STACK" == 1 ]]; then
  if [[ "$ACCEPTANCE_BUILD" == 1 ]]; then
    compose "$APP_COMPOSE_PROJECT" "$APP_ENV_FILE" "$APP_COMPOSE_FILES" up -d --build
    compose "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_ENV_FILE" "$FUNDAMENTAL_COMPOSE_FILES" up -d --build
  else
    compose "$APP_COMPOSE_PROJECT" "$APP_ENV_FILE" "$APP_COMPOSE_FILES" up -d
    compose "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_ENV_FILE" "$FUNDAMENTAL_COMPOSE_FILES" up -d
  fi
fi

require_running_service() {
  local project="$1"
  local env_file="$2"
  local files="$3"
  local service="$4"
  local services
  services="$(compose "$project" "$env_file" "$files" ps --services 2>/dev/null)" || \
    fail "cannot inspect running services for ${project}"
  grep -Fxq "$service" <<<"$services" || fail "${project}/${service} is not running"
}

published_port() {
  local project="$1"
  local env_file="$2"
  local files="$3"
  local service="$4"
  local container_port="$5"
  local binding
  binding="$(compose "$project" "$env_file" "$files" port "$service" "$container_port" 2>/dev/null | head -n 1 | tr -d '\r')" || \
    fail "cannot inspect published port for ${project}/${service}"
  [[ -n "$binding" ]] || fail "${project}/${service} has no published port"
  printf '%s\n' "$binding"
}

extract_url_port() {
  local url="$1"
  local port
  port="${url##*:}"
  port="${port%%/*}"
  [[ "$port" =~ ^[0-9]+$ ]] || fail "URL must include an explicit numeric port: ${url}"
  printf '%s\n' "$port"
}

require_running_service "$APP_COMPOSE_PROJECT" "$APP_ENV_FILE" "$APP_COMPOSE_FILES" "$APP_SERVICE"
require_running_service "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_ENV_FILE" "$FUNDAMENTAL_COMPOSE_FILES" "$FUNDAMENTAL_SERVICE"

app_binding="$(published_port "$APP_COMPOSE_PROJECT" "$APP_ENV_FILE" "$APP_COMPOSE_FILES" "$APP_SERVICE" "$APP_CONTAINER_PORT")"
fundamental_binding="$(published_port "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_ENV_FILE" "$FUNDAMENTAL_COMPOSE_FILES" "$FUNDAMENTAL_SERVICE" "$FUNDAMENTAL_CONTAINER_PORT")"
app_port="${app_binding##*:}"
fundamental_port="${fundamental_binding##*:}"
[[ "$app_port" == "$APP_EXPECTED_PORT" ]] || fail "application port is ${app_port}, expected ${APP_EXPECTED_PORT}"
[[ "$fundamental_port" == "$FUNDAMENTAL_EXPECTED_PORT" ]] || fail "Fundamental port is ${fundamental_port}, expected ${FUNDAMENTAL_EXPECTED_PORT}"
[[ "$(extract_url_port "$APP_URL")" == "$app_port" ]] || fail "APP_URL does not match the current application binding"
[[ "$(extract_url_port "$FUNDAMENTAL_URL")" == "$fundamental_port" ]] || fail "FUNDAMENTAL_URL does not match the current Fundamental binding"

curl --silent --show-error --fail --max-time 10 "${APP_URL%/}/health" >/dev/null || \
  fail "application /health failed at ${APP_URL%/}/health"

ready_json="$(curl --silent --show-error --fail --max-time 10 "${FUNDAMENTAL_URL%/}/readyz")" || \
  fail "Fundamental /readyz failed at ${FUNDAMENTAL_URL%/}/readyz"
if ! READY_JSON="$ready_json" REQUIRE_SEC_IDENTITY_RESOLUTION="$REQUIRE_SEC_IDENTITY_RESOLUTION" python3 - <<'PY'
import json
import os
import sys

try:
    body = json.loads(os.environ["READY_JSON"])
except (KeyError, json.JSONDecodeError) as exc:
    print(f"invalid Fundamental readiness JSON: {exc}", file=sys.stderr)
    raise SystemExit(1)

if body.get("status") != "ready":
    print(f"Fundamental readiness status is {body.get('status')!r}", file=sys.stderr)
    raise SystemExit(1)

if os.environ.get("REQUIRE_SEC_IDENTITY_RESOLUTION") == "1":
    capabilities = body.get("capabilities")
    if not isinstance(capabilities, dict) or capabilities.get("identity_resolution_configured") is not True:
        print("Fundamental identity_resolution_configured capability is false or absent", file=sys.stderr)
        raise SystemExit(1)
PY
then
  fail "Fundamental readiness contract failed"
fi

printf 'acceptance preflight: PASS\n'
printf 'worktree=%s\n' "$repo_root"
printf 'branch=%s\n' "$branch"
printf 'commit=%s\n' "$head"
printf 'app_project=%s service=%s binding=%s url=%s\n' "$APP_COMPOSE_PROJECT" "$APP_SERVICE" "$app_binding" "$APP_URL"
printf 'fundamental_project=%s service=%s binding=%s url=%s\n' "$FUNDAMENTAL_COMPOSE_PROJECT" "$FUNDAMENTAL_SERVICE" "$fundamental_binding" "$FUNDAMENTAL_URL"
printf 'exact_commit=%s sec_identity_required=%s start_stack=%s build=%s allowed_untracked=%s\n' "$REQUIRE_EXACT_COMMIT" "$REQUIRE_SEC_IDENTITY_RESOLUTION" "$START_ACCEPTANCE_STACK" "$ACCEPTANCE_BUILD" "${ALLOWED_UNTRACKED_PATHS:-none}"
