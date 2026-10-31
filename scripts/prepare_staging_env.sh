#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ENV_FILE="${STAGING_SOURCE_ENV_FILE:-$ROOT/.env}"
OUTPUT_ENV_FILE="$ROOT/.env.staging"
COPY_KEYS=(
  STAGING_EMAIL
  STAGING_PASSWORD
  STAGING_OPENROUTER_KEY
  STAGING_SECONDARY_OPENROUTER_KEY
)

if [[ ! -f "$SOURCE_ENV_FILE" ]]; then
  echo "source env file does not exist" >&2
  exit 2
fi

if [[ -e "$OUTPUT_ENV_FILE" || -L "$OUTPUT_ENV_FILE" ]]; then
  echo ".env.staging already exists; inspect it and remove it only when you intend to create a fresh staging environment" >&2
  exit 2
fi

for key in "${COPY_KEYS[@]}"; do
  if ! awk -v key="$key" '
    index($0, "=") > 0 && substr($0, 1, index($0, "=") - 1) == key {
      count++
      value = substr($0, index($0, "=") + 1)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
      if (value == "") empty = 1
    }
    END { exit !(count == 1 && !empty) }
  ' "$SOURCE_ENV_FILE"; then
    echo "source env file must define one non-empty $key" >&2
    exit 2
  fi
done

umask 077
temporary_file="$(mktemp "$ROOT/.env.staging.XXXXXX")"
cleanup() {
  rm -f "$temporary_file"
}
trap cleanup EXIT

{
  printf '%s\n' \
    'APP_ENV=development' \
    'COMPOSE_PROJECT_NAME=value-investment-agent-staging' \
    "INFERENCE_SERVICE_TOKEN=$(openssl rand -hex 32)" \
    "LLM_PROVIDER_SERVICE_TOKEN=$(openssl rand -hex 32)" \
    "SEARCH_SERVICE_TOKEN=$(openssl rand -hex 32)" \
    "DIRECTORY_CURSOR_SECRET=$(openssl rand -hex 32)" \
    "LLM_PROVIDER_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '/+' '_-' | tr -d '\n')" \
    "SEARCH_PROVIDER_ENCRYPTION_KEY=$(openssl rand -base64 32 | tr '/+' '_-' | tr -d '\n')" \
    'POSTGRES_USER=staging' \
    "POSTGRES_PASSWORD=$(openssl rand -hex 32)" \
    'POSTGRES_DB=langgraph' \
    'REDIS_PASSWORD=' \
    'BACKEND_HOST_PORT=18580' \
    'FRONTEND_HOST_PORT=18581' \
    'POSTGRES_HOST_PORT=18582' \
    'REDIS_HOST_PORT=18583' \
    'LLM_PROVIDER_SERVICE_HOST_PORT=18584' \
    'SEARCH_SERVICE_HOST_PORT=18585' \
    'FRONTEND_ALLOWED_ORIGINS=http://127.0.0.1:18581,http://localhost:18581' \
    'STAGING_BASE_URL=http://127.0.0.1:18580' \
    'FRED_API_KEY=' \
    'STAGING_PRIMARY_LABEL=staging-primary' \
    'STAGING_SECONDARY_LABEL=staging-secondary'
  awk -v keys="${COPY_KEYS[*]}" '
    BEGIN { count = split(keys, wanted, " ") }
    index($0, "=") > 0 {
      key = substr($0, 1, index($0, "=") - 1)
      for (i = 1; i <= count; i++) {
        if (key == wanted[i]) {
          print
          next
        }
      }
    }
  ' "$SOURCE_ENV_FILE"
} > "$temporary_file"

chmod 600 "$temporary_file"
if ! ln "$temporary_file" "$OUTPUT_ENV_FILE"; then
  echo ".env.staging was created by another process; no existing file was changed" >&2
  exit 2
fi
rm -f "$temporary_file"
trap - EXIT
printf 'Created .env.staging with mode 0600. Secret values were not printed.\n'
