# Model inference rollout

This runbook covers the private News and SEC FLS inference services. The
backend and inference services have separate Compose lifecycles. Runtime model
loading uses the artifact baked into each image; service startup does not need
Hugging Face registry access.

Issue #109's measurements, recommended limits, and cold-first-call results are
summarized in the [model inference contract](../issue-106-model-inference-contract.md).
The raw evidence index is generated locally under the ignored `reports/issue-109/`
directory when this runbook is executed.

## Preflight

Use a deployment-only `INFERENCE_SERVICE_TOKEN` and keep it out of tracked
files, shell history, logs, and issue comments. The two inference processes
each hold one model copy. Start with four News workers and two FLS workers,
four queued News requests and one queued FLS request, a 1.5 GiB memory limit
per process, and four CPUs per process. #109 reduced both queues after
saturation exposed deadline failures or insufficient deadline headroom with
the earlier settings.

Choose a unique Compose project and unused host ports. The verifier below
defaults to `value-investment-agent-issue109-<UTC time>`, Postgres `15432`,
Redis `16379`, and backend `18109`. It uses an internal runtime network,
project-scoped volumes, and only starts Postgres, Redis, the backend, and the
two inference services. It does not stop or prune other Compose projects.

```bash
INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
ISSUE109_COMPOSE_PROJECT="value-investment-agent-issue109-dennis" \
scripts/verify_model_inference_deployment.sh
```

The script builds the service images with their pinned model artifacts, starts
them on a network without external routing, and waits for `/readyz`. It then
starts the pre-migration backend image, records each inference container ID,
start time, image ID, readiness and model revision, replaces only the backend
with the current image, and compares those records again. The report is JSONL
under `reports/issue-109/`. The script intentionally leaves its isolated
project running for inspection.

## Workload verification

The HTTP benchmark validates successful output shape and correlation IDs,
counts HTTP failures by status and stable error code, measures p50/p95 and
throughput, and samples the service's in-flight and queue gauges from
`/readyz`. It never records input text or the service token. Run it from a
temporary client container on the same Compose network:

```bash
PROJECT=value-investment-agent-issue109-dennis
COMPOSE=(docker compose -p "$PROJECT" \
  -f docker-compose.yml -f compose/verification/docker-compose.issue109-offline.yml)

"${COMPOSE[@]}" run --no-deps --rm -T \
  -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
  -e INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
  --entrypoint /opt/venv/bin/python backend \
  /benchmarks/inference_service_workload.py \
  --base-url http://model-inference-news:8001 \
  --operation news.sentiment \
  --queue-depth 4 --warmup-requests 1 \
  --concurrency 1 2 4 8 --requests-per-level 8 \
  > reports/issue-109/news-service-run-1.json

"${COMPOSE[@]}" run --no-deps --rm -T \
  -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
  -e INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
  --entrypoint /opt/venv/bin/python backend \
  /benchmarks/inference_service_workload.py \
  --base-url http://model-inference-fls:8001 \
  --operation sec.fls \
  --concurrency 1 2 4 8 --requests-per-level 8 \
  --queue-depth 1 --allow-error OVERLOADED --sentences-per-request 16 \
  --warmup-requests 1 \
  > reports/issue-109/fls-service-run-1.json
```

Repeat each side five times, alternating the issue #106 direct-in-process
harness with this service harness. Both sides run one unmeasured warmup request
before recording the same 8 sequential requests,
concurrency levels `1 2 4 8`, 8 requests per level, and 16 FLS sentences per
request. The #106 baseline image is
`sha256:ba6dac071a004c6a85e9bc66164a2f0ce0b2c30594d50be8686aaeaf6ea0ec72`;
use this exact local image ID rather than a mutable tag. Mount only the old
harness into it and set `PYTHONPATH=/app` so imports use the code baked in that
historical image. The comparison runner defaults to this digest and applies
the same four CPU, 1500 MiB, and one PyTorch thread settings used by the
inference services. For News, the baseline command is:

```bash
docker run --rm --network none \
  --entrypoint /opt/venv/bin/python \
  -v "$PWD/scripts/benchmarks:/benchmarks:ro" \
  -e PYTHONPATH=/app \
  -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 \
  -e HF_HOME=/opt/hf-cache-baked \
  -e HF_HUB_CACHE=/opt/hf-cache-baked/hub \
  -e HF_LOCAL_FILES_ONLY=1 -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
  sha256:ba6dac071a004c6a85e9bc66164a2f0ce0b2c30594d50be8686aaeaf6ea0ec72 \
  /benchmarks/finbert_workload.py \
  --warmup-requests 1 --sequential 8 --concurrency 1 2 4 8 --requests-per-level 8
```

Run five alternating baseline/service repetitions for each operation using
the helper. It saves every raw output and image/container identity into a new
directory under the ignored `reports/issue-109/` path:

```bash
ISSUE109_COMPOSE_PROJECT="$PROJECT" \
INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
scripts/benchmarks/run_issue109_comparison.sh
```

The helper uses FLS `--sentences-per-request 16`. Report the median and range
for each latency and throughput value. Keep service startup time separate from
warm inference latency: the baseline records model load and inference warmup
separately, while the service startup interval includes model loading and its
configured warmup.

Run saturation separately. The helper admits four active and four queued
News requests, and two active and one queued FLS request. It saves both the
workload report and repeated `docker stats` samples for the model container.
The workload must observe an `OVERLOADED` response while in-flight and queue
values stay within those limits:

```bash
ISSUE109_COMPOSE_PROJECT="$PROJECT" \
INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
scripts/benchmarks/run_issue109_saturation.sh news

ISSUE109_COMPOSE_PROJECT="$PROJECT" \
INFERENCE_SERVICE_TOKEN="$INFERENCE_SERVICE_TOKEN" \
scripts/benchmarks/run_issue109_saturation.sh fls
```

Compare the highest sampled memory with the 1.5 GiB cgroup cap and compare the
measured latency, throughput, output validity, and error counts with the raw
issue #106 outputs in the local ignored `reports/issue-106/` directory. The service request path adds HTTP
and queue time, so report the measured result without presenting it as a
model-only comparison.

## Failure verification

The contract and focused test suites inject conditions that should not be
forced into a live model container:

| Condition | Verification |
| --- | --- |
| Invalid input, unauthenticated request, malformed response, inference exception, and readiness before model load | `model-inference-service/tests/test_service.py` |
| Queue overload, deadline expiry, queued/active cancellation, and graceful shutdown | `model-inference-service/tests/test_service.py` |
| Service loss, connect failure, deadline, retry budget, cancellation, malformed JSON/result, and News/FLS/Fundamental fallbacks | `finance-agent-core/tests/test_model_inference.py`, `test_error_handling_news.py`, and `test_news_application_use_cases.py` |
| Real endpoint authentication, revision, correlation ID, valid News/FLS output, and service identity across backend replacement | `scripts/verify_model_inference_deployment.sh` plus `scripts/benchmarks/inference_service_workload.py` |

Run the backend and service contract suites after changing the shared contract
or lifecycle:

```bash
uv run --project finance-agent-core pytest \
  finance-agent-core/tests/test_model_inference.py \
  finance-agent-core/tests/test_error_handling_news.py \
  finance-agent-core/tests/test_news_application_use_cases.py

uv run --project model-inference-service pytest model-inference-service/tests/test_service.py
```

## Release and recovery

For a backend-only release, build and replace `backend` in the selected
project. Do not include either inference service in that update command; verify
their container IDs and `/readyz` model revisions remain unchanged. For a
model revision or runtime update, build and replace the affected inference
service separately, then wait for `/readyz` before routing new work. A model
reload occurs when its inference container starts; a backend restart alone
does not reload the inference model.

Rollback a backend-only issue by restoring the previous backend image and
replacing only `backend`. Roll back an inference issue by restoring the
previous inference image and replacing only the affected inference service.
The default image-baked mode needs no model volume for an offline rollback:
restore the prior image, then confirm `/readyz` reports the expected model
revision before resuming traffic. The optional writable-cache mode keeps its
project-scoped model volumes across container replacement; those volumes are
not a substitute for retaining the prior image. See
[`model-artifact-cache.md`](model-artifact-cache.md) for ownership, startup,
restart, and retired-worktree cleanup procedures. Restore traffic through the
existing workflow fallbacks while a service is unavailable; do not add
repeated health probes or retry loops.

After saving and reviewing evidence, stop only the test project:

```bash
docker compose -p "$PROJECT" -f docker-compose.yml \
  -f compose/verification/docker-compose.issue109-offline.yml down
```

This keeps its named volumes. Do not pass `--volumes` until the saved artifacts
are no longer needed.
