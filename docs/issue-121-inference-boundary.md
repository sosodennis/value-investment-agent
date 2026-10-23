# Issue #121 inference boundary

## Deployment endpoint contract

The backend configures one stable private endpoint per task with
`MODEL_INFERENCE_NEWS_URL` and `MODEL_INFERENCE_FLS_URL`. Both default to
`http://localhost:8001`; Compose and production deployment configuration must
set them to service endpoints. Each endpoint may route requests across
replicas. News and Fundamental depend only on the typed backend entrypoint and
do not select hosts, replicas, or model identifiers. `MODEL_INFERENCE_TOKEN`
configures the backend service credential separately from request data.

The service authenticates `Authorization: Bearer <service-token>` before
accepting principal context. The context principal is derived from the
authenticated API session and is never read from browser input. The shared
`internal.v1` metadata wraps the service-owned `inference.v1` schema:

```json
{
  "context": {
    "principal": {"subject_id": "user-123"},
    "correlation_id": "request-123",
    "contract_version": "internal.v1",
    "deadline_at": "2026-10-23T18:30:00Z"
  },
  "schema_version": "inference.v1",
  "operation": "news.sentiment",
  "deadline_ms": 500,
  "input": {"text": "Revenue improved."}
}
```

Only `news.sentiment` and `sec.fls` are supported. Responses and failures
include `correlation_id` and `contract_version: internal.v1`; service payloads
continue to include `schema_version: inference.v1`. The absolute deadline is
authoritative and the existing operation-specific millisecond budget remains
an upper bound. `GET /readyz` implements the shared readiness response.
`GET /readyz/details` exposes service-owned model revision and queue details
for deployment verification.

The service image imports the canonical shared package from the Docker
BuildKit named context `internal-contracts`, sourced from
`finance-agent-core/src/shared`. Compose must provide that additional context
while keeping `model-inference-service` as the primary build context. This
packages the accepted shared models and authentication function without
copying a second implementation into the service.

## Prior evidence audit

- #105 defines the independent lifecycle and explicitly separates model
  inference from LLM Provider responsibilities.
- #106 records the caller inventory, service contract, limits, retries,
  fallbacks, and retained backend workloads. The SEC dense retriever still
  uses `SentenceTransformer` and the dependency matcher remains backend-owned.
- #107 owns pinned model loading, warmup, bounded queues, cancellation,
  readiness, stable errors, and redacted telemetry in the service.
- #108 owns the typed backend facade, one-deadline retry policy, and existing
  News/Fundamental fallback behavior.
- #109 records independent backend replacement, offline artifact startup,
  capacity tests, and the cold first-call deadline result. This change reuses
  that lifecycle and capacity evidence; the changed readiness representation
  is covered by service contract tests. It does not repeat the two-replica
  routing proof assigned to #126.

## Acceptance report

- Base SHA: `275035bce879dce8cd6d0e94af4c02cb2a919efc`.
- Result SHA: recorded by the implementation commit referenced in the PR.
- Verdict: PASS for focused service/client boundary checks. Compose validation is
  BLOCKED by the shared root configuration requiring `LITELLM_MASTER_KEY`.
- Backend ML dependencies: retained. The repository inventory still contains
  backend-owned embedding and spaCy workloads, so shared ML dependencies were
  not removed.
- Docker artifacts: no images or containers were built or started for this
  issue. Python virtual environments created by `uv` are ignored and local to
  this worktree.

Validation evidence:

- PASS: `uv run pytest finance-agent-core/tests/test_model_inference.py -q`
  (`30 passed`).
- PASS: `uv run pytest model-inference-service/tests/test_service.py -q`
  (`21 passed`).
- PASS: `uv run ruff check model-inference-service/src
  model-inference-service/tests`.
- PASS: `python3 -m compileall -q model-inference-service/src`.
- PASS: `python3 scripts/architecture_guard.py` (`no boundary violations`).
- BLOCKED: `docker compose config --quiet` because the shared root Compose
  requires `LITELLM_MASTER_KEY`; no Docker image or container was started.
- NOT RERUN: #109 deployment probes and #126 replica routing proof. This
  change does not alter model lifecycle or routing and #126 owns the routing
  proof.
