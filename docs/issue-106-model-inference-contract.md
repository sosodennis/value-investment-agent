# Model inference inventory and contract

This document records the current backend workload and the proposed private inference service contract for issue #106. It is a reference for the service owner and backend caller owners. It does not implement the service or migrate callers.

## Decision summary

The first service scope has two operations:

| Operation | Current model | Initial worker limit | Initial queue | Memory reservation |
| --- | --- | ---: | ---: | ---: |
| `news.sentiment` | `project-aps/finbert-finetune` | 4 in flight | 8 | 1.25 GiB |
| `sec.fls` | `yiyanghkust/finbert-fls` | 2 in flight | 8 | 1.25 GiB |

Run one model process per operation and replica. Each process owns its model copy. Start with one News worker and one FLS worker per 10-core host. Do not add worker processes until the service reruns the benchmark after setting a deliberate PyTorch thread count.

The measured container RSS peak was about `930 MiB` for News and `1.07 GiB` for FLS. The `1.25 GiB` reservation leaves room for allocator and request overhead. Set a `1.5 GiB` hard cgroup limit per model process and alert at 80 percent of the reservation. The limit is a recommendation from the measured image runtime, not a production guarantee.

## Current workload inventory

The inventory includes every model artifact referenced by the backend. The first service scope covers the two FinBERT classifiers. The embedding and spaCy workloads remain backend-local because their current call patterns are different and this issue found no concrete lifecycle benefit that justifies adding them to the first API.

| Workload | Caller and call shape | Load and warmup | Fallback or cache | Evidence |
| --- | --- | --- | --- | --- |
| News sentiment | News analyst loops over articles. It calls `is_available()` and then runs synchronous `analyze` in `asyncio.to_thread`. | API lifespan warms the singleton when `NEWS_FINBERT_WARMUP` is enabled. | If unavailable, the article uses the basic LLM chain. The analyzer is a process singleton. | `finance-agent-core/src/agents/news/application/analysis_service.py:124-180`, `finance-agent-core/src/infrastructure/sentiment/finbert_sentiment_provider.py:33-121` |
| SEC FLS sentence filter | SEC forward-signal extraction calls the synchronous filter with a sentence list. The filter prefilters, batches at 32, and caches up to 4096 sentence predictions. | API lifespan warms the classifier when `SEC_TEXT_FLS_WARMUP` is enabled. | Load or inference failure returns the lexical rule filter. | `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/filtering/fls_filter.py:50-121`, `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/filtering/fls_filter.py:31-36` |
| SEC FinBERT direction review | Forward-signal postprocessing can call the shared News FinBERT analyzer for `growth_outlook` and `margin_outlook`. | It uses the same News singleton and is not a second model artifact. | Numeric evidence, unsupported metrics, low confidence, neutral labels, and unavailable inference leave the baseline direction unchanged. | `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/postprocess/finbert_direction.py:75-148` |
| SEC dense retrieval | Hybrid retrieval calls a lazy `SentenceTransformer` model for corpus and query embeddings. | No API lifespan warmup is wired for this loader. | Empty dense rankings leave sparse BM25 ranking in the RRF merge. | `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/retrieval/hybrid_retriever_dense_service.py:36-142`, `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/retrieval/hybrid_retriever.py:79-105` |
| Council sycophancy embedding | Moderator calls FastEmbed synchronously through `asyncio.to_thread`. | The provider is lazy and creates an ONNX `TextEmbedding` instance on first use. | No local provider fallback was observed. The workload stays outside the first service scope. | `finance-agent-core/src/agents/debate/application/debate_service.py:276-296`, `finance-agent-core/src/agents/debate/infrastructure/sycophancy/sycophancy_detector_provider.py:14-58` |
| SEC dependency matcher | SEC extraction can use spaCy dependency parsing. | API lifespan warms `en_core_web_sm` when `SEC_TEXT_DEPENDENCY_WARMUP` is enabled. | Missing spaCy or parser model skips the dependency layer. | `finance-agent-core/api/server.py:200-224`, `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/matching/matchers/dependency_signal_matcher.py:193-258` |

The current API process therefore holds shared model state and rebuilds all warm state with the backend process. A future private service moves only the two first-scope operations across the deployment boundary. The News and Fundamental modules keep domain ports and do not import HTTP wire types.

## Measurements

The repeatable harnesses are `scripts/benchmarks/finbert_workload.py`, `scripts/benchmarks/fls_workload.py`, and `scripts/benchmarks/model_inventory.py`. Raw JSON is in `reports/issue-106/`. The container measurements used image `via-llm-stage-backend:latest`, image ID `sha256:ba6dac071a004c6a85e9bc66164a2f0ce0b2c30594d50be8686aaeaf6ea0ec72`, Python `3.11.17`, Linux arm64, offline Hugging Face cache, and the current branch mounted at `/work`.

The News benchmark ran five fresh containers. Each run loaded the model once, issued eight sequential calls, then issued eight calls at each concurrency level with four distinct texts. The median and range were:

| News metric | c1 | c2 | c4 | c8 |
| --- | ---: | ---: | ---: | ---: |
| p50 latency | 75.3 ms | 102.1 ms | 140.4 ms | 194.1 ms |
| p95 latency | 84.6 ms | 107.0 ms | 148.4 ms | 215.8 ms |
| throughput | 13.1 RPS | 19.4 RPS | 27.5 RPS | 36.5 RPS |

News model load was `18.5 s` median, with a `15.1 to 20.6 s` range. RSS after load was `475.8 MiB` median. RSS after concurrency reached `892 MiB` median and `931 MiB` at the highest observed run. All 160 measured News calls succeeded and returned labels and scores.

The FLS benchmark ran five valid fresh containers. Each request sent 16 unique sentences, which avoids the existing prediction cache. The median and range were:

| FLS metric | c1 | c2 | c4 | c8 |
| --- | ---: | ---: | ---: | ---: |
| p50 latency | 207.0 ms | 309.8 ms | 523.4 ms | 834.6 ms |
| p95 latency | 229.3 ms | 353.5 ms | 596.3 ms | 922.5 ms |
| throughput | 4.7 RPS | 6.3 RPS | 7.2 RPS | 8.6 RPS |

FLS model load was `15.4 s` median. Warmup inference was `136 ms` median. RSS after load was `877 MiB` median. RSS after concurrency was `1.06 GiB` median. All 160 measured FLS calls succeeded. One earlier FLS run was rejected from the result set because the first harness version called a package function that the facade did not export and recorded `AttributeError` for every request.

The inventory probe found these artifacts in the baked image:

| Artifact | Cold probe | Load or first-call time | Peak RSS | Result |
| --- | --- | ---: | ---: | --- |
| `project-aps/finbert-finetune` | container | 9.9 s | 478 MiB | available |
| `yiyanghkust/finbert-fls` | container | 8.2 s | 821 MiB | available |
| `sentence-transformers/all-MiniLM-L6-v2` | container | 11.9 s | 578 MiB | available |
| `sentence-transformers/all-MiniLM-L6-v2` via FastEmbed | container | 312 ms | 216 MiB | available |
| `en_core_web_sm` | container | 4.4 s | 434 MiB | available |

The same probes in the host `uv` environment found only News FinBERT available. FLS, dense retrieval, and FastEmbed reported missing local artifacts. The host result is retained in the raw JSON to show why a cache-complete image is required for a meaningful service benchmark.

Image build and runtime cache seeding are separate from process loading. The existing image contains about `2.2 GiB` of baked cache. A direct entrypoint seed into a fresh container failed with `No space left on device` after about `5.03 s`, before model loading. The full branch-specific Compose build did not produce an image because the dependency layer was still being rebuilt. Therefore the container workload numbers are valid for the current code mounted into the existing cache-complete arm64 runtime, while the cache-seed and full Compose startup gates remain open.

The measured limiter is CPU inference and PyTorch thread contention. News gains only about one third more throughput from c4 to c8 while p95 rises from `148 ms` to `216 ms`. FLS gains only `1.2 RPS` from c2 to c4 while p95 rises from `354 ms` to `596 ms` and RSS reaches `1.06 GiB`. The benchmark checks counted errors and validated non-empty labels or selected predictions. It did not measure network transport because the current backend has no inference service endpoint.

## HTTP contract

Expose a private versioned endpoint:

```http
POST /v1/inference
Authorization: Bearer <service-token>
X-Request-ID: 01J...
Content-Type: application/json
```

The service accepts this body shape:

```json
{
  "schema_version": "inference.v1",
  "operation": "news.sentiment",
  "deadline_ms": 500,
  "input": {
    "text": "Management expects revenue growth to improve."
  }
}
```

The allowed `operation` values are `news.sentiment` and `sec.fls`. The caller never sends a model identifier. The operation registry resolves the model name, tokenizer, label map, and pinned revision. Reject unknown operations and extra fields with `INVALID_ARGUMENT`.

`news.sentiment` accepts one UTF-8 text value up to 12,000 characters. The service rejects an empty value and a value above the limit. The response contains `label`, `confidence`, `scores`, `operation`, `model_revision`, and the echoed `request_id`.

`sec.fls` accepts one to 120 sentences. Each sentence is at most 2,000 characters. The service batches at most 32 sentences per model call and returns predictions in input order. Each prediction contains `keep`, `confidence` when the model provides it, and `model_revision`. The current backend's lexical fallback is a caller-visible degraded path, so a model failure does not become a successful model response.

Every successful response has this envelope:

```json
{
  "schema_version": "inference.v1",
  "request_id": "01J...",
  "operation": "news.sentiment",
  "model_revision": "<allowlisted-model-revision>",
  "result": {"label": "positive", "confidence": 0.99, "scores": {}}
}
```

The exact Hugging Face revision and artifact digest are deployment configuration, not caller input. Current backend code uses floating model names and does not record a revision. The service manifest must pin a commit revision and tokenizer revision before production rollout, and must return both in the response or expose them from readiness.

## Error, deadline, cancellation, and retry rules

Use one stable error envelope for every non-2xx response:

```json
{
  "schema_version": "inference.v1",
  "request_id": "01J...",
  "error": {
    "code": "OVERLOADED",
    "message": "inference capacity is full",
    "retryable": true,
    "retry_after_ms": 250
  }
}
```

| Code | HTTP | Meaning | Retry |
| --- | ---: | --- | --- |
| `INVALID_ARGUMENT` | 400 | Schema, operation, text, batch, or deadline limit failed. | No. |
| `UNAUTHENTICATED` | 401 | Private service token is absent or invalid. | No. |
| `MODEL_NOT_READY` | 503 | The allowlisted model revision is not loaded. | Yes after readiness, with backoff. |
| `OVERLOADED` | 429 | In-flight and bounded queue capacity are full. | Yes after `retry_after_ms`. |
| `DEADLINE_EXCEEDED` | 504 | The end-to-end deadline expired before a result. | One retry only when the caller has a new deadline and the request did not start. |
| `CANCELLED` | 499 | The client cancelled or disconnected. | No. |
| `UNAVAILABLE` | 503 | Draining, process restart, transport failure, or dependency outage. | Yes, once. |
| `INFERENCE_FAILED` | 500 | Model execution or output validation failed. | No by default. |

`deadline_ms` is optional. Defaults are 500 ms for News and 750 ms for FLS. The service caps them at 1,000 ms for News and 1,500 ms for FLS. Queue wait and model execution use the same monotonic deadline. A request that cannot enter a worker before the queue budget expires returns `DEADLINE_EXCEEDED`.

Queued cancellation removes the request immediately. Running cancellation is cooperative. The service marks the request cancelled, stops publishing its result, and releases the capacity slot only when the current PyTorch call returns. The service does not kill a worker thread or process for one cancelled request.

The backend uses one retry at most. It retries `MODEL_NOT_READY`, `OVERLOADED`, and `UNAVAILABLE` when `retryable` is true. It waits for the server's `retry_after_ms`, capped at 500 ms, and uses a fresh deadline budget. It does not retry `INVALID_ARGUMENT`, `UNAUTHENTICATED`, `CANCELLED`, or `INFERENCE_FAILED`. The backend keeps the same `X-Request-ID` across the retry. The service deduplicates an active request ID and may return a completed response from a short 60-second idempotency cache. This prevents a timeout from creating unbounded duplicate compute.

Current workflow fallbacks remain explicit during migration. News treats `MODEL_NOT_READY`, `UNAVAILABLE`, `DEADLINE_EXCEEDED`, and `INFERENCE_FAILED` as no FinBERT result and uses its basic LLM chain. SEC FLS uses the lexical filter for the same model errors. The service must not return a fabricated neutral label or an empty successful prediction for those cases.

## Capacity and operations

Use one bounded queue per operation. News starts with four in-flight requests and eight queued requests. FLS starts with two in-flight requests and eight queued requests. Return `OVERLOADED` as soon as the queue is full. Do not allow an unbounded semaphore waiter list.

The worker count is a memory calculation. For each operation, reserve one full model process per worker and multiply the measured per-process reservation by the worker count. Keep at least 25 percent host memory for the backend, OS, and non-model work. A ten-core host starts with one News worker and one FLS worker. Scaling a model to two workers roughly duplicates its model memory even when the artifact is read from a shared cache.

Provide `GET /livez` for process liveness and `GET /readyz` for model revision, tokenizer revision, queue state, and accepting status. Readiness is false until the configured revision is loaded and true only while the process accepts new work. On shutdown, set accepting to false, drain only admitted requests until their deadlines, cancel queued requests, and then exit. Prediction callers do not make a health preflight call.

Require a private service token or mTLS at the service boundary. Generate or forward a request correlation ID. Emit counters and histograms for operation, model revision, result code, queue wait, inference time, deadline, cancellation, and retry. Never emit request text, authorization headers, or full model output in logs or metric labels.

## Proposed module ownership

The future vertical slice belongs at `finance-agent-core/src/model_inference/`:

| Module | Owner |
| --- | --- |
| `entrypoint.py` | Public backend port used by News and Fundamental callers. |
| `interface/contracts.py` | Typed request and result ports. It does not expose HTTP types to agents. |
| `application/service.py` | Deadline propagation, bounded retry, cancellation, and degraded-path selection. |
| `domain/operation_registry.py` | Allowed operations, input limits, model revision metadata, and label maps. |
| `domain/errors.py` | Stable internal error categories and retryability. |
| `infrastructure/client.py` | Private HTTP transport, authentication, correlation, and response decoding. |
| `infrastructure/metrics.py` | Sanitized service-call metrics. |
| `api/` in the separate service | HTTP schemas, auth, health, queue admission, and model workers. |

News and Fundamental depend on the port in `model_inference.entrypoint` or a shared application contract. They do not depend on `FastAPI`, HTTP status codes, queue internals, or model identifiers. A backend rebuild can then restart its caller process while the inference service keeps its model cache and readiness state. The deployment platform is intentionally unspecified; the boundary is a private versioned HTTP service, and the platform must provide the artifact cache, memory limits, and service-token transport.

## Scope fence

This change adds documentation, benchmark harnesses, raw measurements, and the decision trail for issue #106. It does not implement `model_inference`, change existing callers, or modify the work assigned to issues #107 through #109.
