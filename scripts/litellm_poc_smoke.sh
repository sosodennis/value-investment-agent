#!/bin/sh
set -eu

gateway_url="${LLM_GATEWAY_BASE_URL:-http://localhost:4000}"
: "${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY before running the smoke check}"

curl -fsS "${gateway_url}/health/liveliness" >/dev/null
models_json="$(curl -fsS \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  "${gateway_url}/v1/models")"

python3 -c '
import json
import sys

models = json.loads(sys.stdin.read()).get("data", [])
assert any(item.get("id") == "openrouter-default" for item in models), models
' <<EOF
${models_json}
EOF

printf '%s\n' "LiteLLM OpenRouter gateway health and model alias checks passed."
