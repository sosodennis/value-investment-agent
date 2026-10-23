# Model Inference Service

This is the private, task-specific service for the two workloads approved by issue #106:

- `news.sentiment` uses the pinned `project-aps/finbert-finetune` revision `2db55b5439cef6253c12a4973f3a9e823ff90b79`.
- `sec.fls` uses the pinned `yiyanghkust/finbert-fls` revision `443586dc31c765c0aaf1c4daaed8cf3643c92fa5`.

Compose runs one service process per operation (`model-inference-news` and `model-inference-fls`) so model memory is not multiplied by an in-process multi-model registry. Each process owns and loads only its operation's model and uses a separate persistent artifact-cache volume, so concurrent first starts cannot race while seeding the cache.

Build with prepared artifacts before offline startup:

```bash
BAKE_INFERENCE_MODELS=1 \
INFERENCE_SERVICE_TOKEN=local-development-token \
docker compose -p value-investment-agent up -d --build \
  model-inference-news model-inference-fls
```

The service does not publish an inference host port. The backend reads `MODEL_INFERENCE_NEWS_URL` and `MODEL_INFERENCE_FLS_URL`, each defaulting to `http://localhost:8001` outside Compose. Deployments set each variable to a stable private service endpoint. An endpoint may route an operation across one or more replicas; agent and workflow code do not name hosts or replicas. `MODEL_INFERENCE_TOKEN` is sent separately as the backend service credential.

`GET /livez` reports process liveness. `GET /readyz` returns the shared `internal.v1` readiness shape and becomes ready only after the configured model is loaded and warm. `GET /readyz/details` exposes operation readiness, queue state, and model revision for deployment checks. Inference requests require `Authorization: Bearer` and carry an authenticated `context` with `principal.subject_id`, `correlation_id`, `contract_version: internal.v1`, and an absolute UTC `deadline_at`. The operation payload remains service-owned and uses `schema_version: inference.v1`; only `news.sentiment` and `sec.fls` are accepted. Responses and errors echo the correlation ID and internal contract version. The request ID header is a transport hint; the authenticated context is authoritative.

The private `/metrics/` endpoint exports request outcomes, queue-wait and inference histograms, in-flight calls, and queue size. Request logs include the request ID, operation, pinned revision, outcome, queue wait, in-flight count, and inference duration; they never include input text. A request ID can be replayed with identical input: active requests share one execution and successful responses are cached for 60 seconds. Reusing an ID with different input is invalid. The workload-tested default capacity is four in-flight plus four queued requests for News and two in-flight plus one queued request for FLS. The bounded queues return `OVERLOADED` for work beyond those limits; the measured queue limits are documented in `reports/issue-109/verification-summary.md`. The bounded queue, monotonic deadline, cooperative cancellation, and stable error envelope are implemented in `src/model_inference_service/runtime.py` and `app.py`.

Each container runs one process and holds one model copy. The issue #106 arm64 workload measured peak RSS of about 930 MiB for News and 1.07 GiB for FLS. Compose reserves 1.25 GiB and enforces a 1.5 GiB memory limit per replica, with four CPUs. Start with one News replica and one FLS replica per 10-core host; adding a replica adds another model copy and requires the same memory budget.
