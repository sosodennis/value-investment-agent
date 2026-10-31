# Issue 126 Acceptance Report

> Superseded by issue #189. This historical report records the 2026-10-24
> capability deployment experiment; its standalone LiteLLM gateway topology
> and gateway verification commands are retired. The canonical topology now
> runs the embedded LiteLLM runtime inside `llm-provider-service`.

Date: 2026-10-24

## Result

**Historical PASS for the independent capability deployment gates.** The LLM
Provider, Model Inference, and Search services ran as separate Compose services
with two replicas each. Backend replacement and capability restarts were
independent. The standalone gateway experiment is no longer a supported
runtime path and is not evidence for the current topology.

## Revisions

- Baseline: `af25f9d634fcb98f2372dd4892e9d13110c92175` (`origin/main`)
- Capability implementation: `da46e27210a134ecd244aba816f7d07afb079051`
- Final verification tooling: `afde1da`; final reviewed registry pin: `35aaa1b`
- Historical LiteLLM image: `ghcr.io/berriai/litellm@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7` (`v1.106.2`, ARM64). The image was used by the retired gateway experiment.

## Verification matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Compose configuration | PASS | `docker compose ... config --quiet` |
| Service images | PASS | LLM Provider, Search, and current-source model-inference verification images built |
| Replica readiness | PASS | Two ready LLM Provider, Search, News Inference, and FLS Inference replicas |
| Internal authentication | PASS | Missing bearer token returns `internal_auth_missing`; valid service tokens accepted |
| Deadline contract | PASS | Expired Search, LLM, and inference contexts return bounded 504 errors |
| Redaction | PASS | Probe inputs and disposable secrets absent from error responses |
| Search settings persistence | PASS | Write/read survives independent Search restart |
| Backend-only replacement | PASS | Backend container force-recreated while capability container IDs stayed unchanged |
| Capability restart | PASS | LLM Provider and both inference operations become ready after independent restart |
| Version skew | PASS | Previous Search image ran beside current replicas and passed `/readyz` |
| Failure coverage | PASS | Focused suites cover overload, cancellation, malformed responses, ownership isolation, retry budgets, cooldowns, and redaction |
| Retired gateway database migration | HISTORICAL | v1.106.2 applied all Prisma migrations on a disposable `litellm` database |
| Retired gateway liveness and auth | HISTORICAL | `/health/liveliness`, authenticated `/v1/models`, authenticated `/model/info`, and unauthenticated 401 probe |

The capability run was executed with:

```bash
ISSUE126_COMPOSE_PROJECT=value-investment-agent-issue126-k \
ISSUE126_REPORT=reports/issue-126/deployment-20261024k.jsonl \
ISSUE126_HEALTH_TIMEOUT_SECONDS=420 \
./scripts/verify_capability_deployment.sh
```

The capability runner used a unique Compose project name and cleaned its own
containers and networks on exit. It did not run global Docker pruning or
remove shared volumes.

## Fixes made during acceptance

- Serialized LLM Provider schema creation and compatibility seeding with a
  PostgreSQL transaction advisory lock. Concurrent replica startup previously
  raced on PostgreSQL relation types and produced a `pg_type_typname_nsp_index`
  violation.
- Corrected the LLM Provider image source copy so the ASGI module is placed at
  `src/llm_provider_service` rather than nested under an extra `src` path.
- Renamed the production OpenRouter validator from `test_openrouter_key` to
  `validate_openrouter_key`; the old name caused pytest to collect it as a
  fixture-based test and fail the service suite.
- Pinned LiteLLM to v1.106.2. The previous v1.106.1 image failed fresh Prisma
  migration `20260131150814` with P3009. v1.106.2 completed the same fresh
  database migration set successfully.

## Focused checks

- LLM Provider: `73 passed, 1 skipped`; Ruff check and format pass.
- Search: `106 passed, 1 skipped`.
- Model Inference: `21 passed`.
- `python3 scripts/architecture_guard.py`: passed with no boundary violations.
- Compose config and `git diff --check`: passed.

## Remaining follow-ups

- #126 does not close the broader #118 or repository architecture epic #101.
  Those remain open for future capability inventory and architecture migration
  work.
- Current embedded-runtime acceptance is tracked by #189, including provider
  service replica checks, fault injection, and secret/tenant isolation.
