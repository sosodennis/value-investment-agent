#!/bin/sh
set -eu

gateway_url="${LLM_GATEWAY_BASE_URL:-http://localhost:4000}"
: "${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY before running the smoke check}"

curl -fsS "${gateway_url}/health/liveliness" >/dev/null
printf '%s\n' "LiteLLM gateway is live. Add a tested OpenRouter key through the project settings API before sending model requests."
