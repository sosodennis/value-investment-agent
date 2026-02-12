#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_CACHE_DIR_DEFAULT="${ROOT_DIR}/.cache/uv"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$UV_CACHE_DIR_DEFAULT}"

mkdir -p "${UV_CACHE_DIR}"

cd "${ROOT_DIR}/finance-agent-core"
uv run python scripts/export_openapi.py

cd "${ROOT_DIR}/frontend"
npm run generate:api-contract

echo "Contract generation completed."
