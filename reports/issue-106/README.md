# Issue 106 measurement artifacts

The JSON files in this directory are raw outputs from the benchmark scripts. They include the environment, model availability, latency samples, error counts, labels or selected predictions, and RSS peak values.

Run the host probes with the repository Python environment:

```bash
HF_HOME="$HOME/.cache/huggingface" \
HF_HUB_CACHE="$HOME/.cache/huggingface/hub" \
HF_LOCAL_FILES_ONLY=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
uv run --project finance-agent-core python scripts/benchmarks/model_inventory.py \
  --workload news_finbert
```

Run the cache-complete arm64 image probe with the current checkout mounted into `/work`:

```bash
docker run --rm --entrypoint /opt/venv/bin/python \
  -v "$PWD:/work" -w /work \
  -e HF_HOME=/opt/hf-cache-baked \
  -e HF_HUB_CACHE=/opt/hf-cache-baked/hub \
  -e SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache-baked/hub \
  -e FASTEMBED_CACHE_PATH=/opt/hf-cache-baked/hub \
  -e HF_LOCAL_FILES_ONLY=1 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  via-llm-stage-backend:latest \
  scripts/benchmarks/model_inventory.py --workload sec_fls
```

Run the News and FLS concurrency measurements with the same image:

```bash
docker run --rm --entrypoint /opt/venv/bin/python \
  -v "$PWD:/work" -w /work \
  -e HF_HOME=/opt/hf-cache-baked \
  -e HF_HUB_CACHE=/opt/hf-cache-baked/hub \
  -e SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache-baked/hub \
  -e FASTEMBED_CACHE_PATH=/opt/hf-cache-baked/hub \
  -e HF_LOCAL_FILES_ONLY=1 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  via-llm-stage-backend:latest \
  scripts/benchmarks/finbert_workload.py --sequential 8 \
  --concurrency 1 2 4 8 --requests-per-level 8

docker run --rm --entrypoint /opt/venv/bin/python \
  -v "$PWD:/work" -w /work \
  -e HF_HOME=/opt/hf-cache-baked \
  -e HF_HUB_CACHE=/opt/hf-cache-baked/hub \
  -e SENTENCE_TRANSFORMERS_HOME=/opt/hf-cache-baked/hub \
  -e FASTEMBED_CACHE_PATH=/opt/hf-cache-baked/hub \
  -e HF_LOCAL_FILES_ONLY=1 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  via-llm-stage-backend:latest \
  scripts/benchmarks/fls_workload.py --sequential 8 \
  --concurrency 1 2 4 8 --requests-per-level 8 --sentences-per-request 16
```

The direct image command reuses the existing baked layer and does not measure image download or entrypoint cache seeding. The cache seed check is separate. It copies the approximately `2.2 GiB` baked cache into a fresh runtime cache and currently fails with `No space left on device` in Docker Desktop. A complete Compose startup benchmark remains open until the backend image is rebuilt from this branch and the cache volume has enough space.
