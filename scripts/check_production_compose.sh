#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

full_env="$TMP_DIR/full.env"
missing_search_token_env="$TMP_DIR/missing-search-token.env"
missing_search_encryption_env="$TMP_DIR/missing-search-encryption.env"
printf '%s\n' \
  'LLM_PROVIDER_SERVICE_TOKEN=production-contract-llm-token' \
  'SEARCH_SERVICE_TOKEN=production-contract-search-token' \
  'LLM_PROVIDER_ENCRYPTION_KEY=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=' \
  'SEARCH_PROVIDER_ENCRYPTION_KEY=BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB=' \
  'DIRECTORY_CURSOR_SECRET=production-contract-directory-secret' \
  'AUDIT_CURSOR_SECRET=production-contract-audit-secret' \
  'FRED_API_KEY=production-contract-fred-key' >"$full_env"
grep -v '^SEARCH_SERVICE_TOKEN=' "$full_env" >"$missing_search_token_env"
grep -v '^SEARCH_PROVIDER_ENCRYPTION_KEY=' "$full_env" >"$missing_search_encryption_env"

compose() {
  local env_file="$1"
  shift
  docker compose --env-file "$env_file" -f docker-compose.yml -f docker-compose.production.yml "$@"
}

if compose "$missing_search_token_env" config --quiet >/dev/null 2>&1; then
  echo "production Compose unexpectedly accepted a missing SEARCH_SERVICE_TOKEN" >&2
  exit 1
fi

if compose "$missing_search_encryption_env" config --quiet >/dev/null 2>&1; then
  echo "production Compose unexpectedly accepted a missing SEARCH_PROVIDER_ENCRYPTION_KEY" >&2
  exit 1
fi

resolved="$TMP_DIR/production-compose.json"
compose "$full_env" config --format json >"$resolved"

jq -e '
  .services.backend.environment.SEARCH_SERVICE_TOKEN == "production-contract-search-token"
  and .services["search-service"].environment.SEARCH_SERVICE_TOKEN == "production-contract-search-token"
  and .services["search-service"].environment.SEARCH_PROVIDER_ENCRYPTION_KEY == "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
  and ([.services[].environment[]?] | index("local-development-only-token") | not)
' "$resolved" >/dev/null

echo "production Compose secret contract passed"
