#!/bin/sh
set -eu

gateway_url="${LLM_GATEWAY_BASE_URL:-http://localhost:4000}"
: "${LITELLM_MASTER_KEY:?set LITELLM_MASTER_KEY before running the smoke check}"

curl --fail --silent --show-error --retry 3 \
  "${gateway_url}/health/liveliness" >/dev/null

models_json="$(mktemp)"
trap 'rm -f "$models_json"' EXIT
curl --fail --silent --show-error --retry 3 \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  "${gateway_url}/v1/models" >"$models_json"
curl --fail --silent --show-error --retry 3 \
  -H "Authorization: Bearer ${LITELLM_MASTER_KEY}" \
  "${gateway_url}/model/info" >/dev/null

if [ -n "${POC_MODEL_ALIAS:-}" ]; then
  if ! grep -q "${POC_MODEL_ALIAS}" "$models_json"; then
    printf '%s\n' "Configured model alias was not returned by LiteLLM: ${POC_MODEL_ALIAS}" >&2
    exit 1
  fi
  printf '%s\n' "LiteLLM is live and returned model alias ${POC_MODEL_ALIAS}."
else
  printf '%s\n' "LiteLLM is live; authenticated /v1/models and /model/info checks passed."
  printf '%s\n' "Set POC_MODEL_ALIAS to assert a user pool alias after adding a key through the project settings API."
fi
