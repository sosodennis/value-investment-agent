#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_CACHE_DIR_DEFAULT="${ROOT_DIR}/.cache/uv"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$UV_CACHE_DIR_DEFAULT}"

mkdir -p "${UV_CACHE_DIR}"

cd "${ROOT_DIR}/finance-agent-core"
uv run python ../scripts/generate-fiscal-wire-contract.py
uv run --frozen python ../scripts/generate-statement-reader-schema.py
uv run python scripts/export_openapi.py

uv run --frozen --directory "${ROOT_DIR}/fundamental-service" python "${ROOT_DIR}/scripts/check-fiscal-wire-contract.py"

cd "${ROOT_DIR}/frontend"
npm run generate:api-contract

cd "${ROOT_DIR}"
uv run --directory "${ROOT_DIR}/search-service" python scripts/generate_openapi.py

echo "Contract generation completed."
