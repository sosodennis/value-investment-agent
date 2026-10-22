#!/bin/sh
set -eu

runtime_cache="${HF_HOME:-/opt/hf-cache}"
baked_cache="${HF_BAKED_CACHE:-/opt/hf-cache-baked}"
if [ -d "${baked_cache}" ]; then
  mkdir -p "${runtime_cache}"
  if [ -z "$(ls -A "${runtime_cache}" 2>/dev/null || true)" ]; then
    cp -a "${baked_cache}/." "${runtime_cache}/"
  else
    cp -an "${baked_cache}/." "${runtime_cache}/"
  fi
fi

export HF_HUB_CACHE="${HF_HUB_CACHE:-${runtime_cache}/hub}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HUB_CACHE}}"
export PYTHONPATH="/app/src${PYTHONPATH:+:${PYTHONPATH}}"

exec python -m uvicorn model_inference_service.app:app --host 0.0.0.0 --port 8001
