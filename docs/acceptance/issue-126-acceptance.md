# Issue 126 Acceptance Report

Date: 2026-10-24

## Result

**PASS for the independent capability deployment gates.** The LLM Provider,
Model Inference, and Search services ran as separate Compose services with two
replicas each. Backend replacement and capability restarts were independent.
LiteLLM gateway verification also passed after updating the pinned image to
LiteLLM v1.106.2.

The gateway and capability checks run as separate isolated Compose projects.
The Docker VM has approximately 8.3 GB available and is shared by other
worktrees; combining all replicas with LiteLLM caused an observed Docker OOM
(`exit 137`). That resource-pressure experiment is retained as an environment
finding, not a product pass/fail result.

## Revisions

- Baseline: `af25f9d634fcb98f2372dd4892e9d13110c92175` (`origin/main`)
- Capability implementation: `da46e27210a134ecd244aba816f7d07afb079051`
- Final verification tooling: `afde1da`; final reviewed registry pin: `35aaa1b`
- LiteLLM image: `ghcr.io/berriai/litellm@sha256:7294b90f868c5c38c99b83021c7ba46f9b439e95f8e32964c925c7d2563a03f7` (`v1.106.2`, ARM64)

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
| LiteLLM fresh database migration | PASS | v1.106.2 applied all Prisma migrations on a disposable `litellm` database |
| LiteLLM liveness and auth | PASS | `/health/liveliness`, authenticated `/v1/models`, authenticated `/model/info`, and unauthenticated 401 probe |

The capability run was executed with:

```bash
ISSUE126_COMPOSE_PROJECT=value-investment-agent-issue126-k \
ISSUE126_REPORT=reports/issue-126/deployment-20261024k.jsonl \
ISSUE126_HEALTH_TIMEOUT_SECONDS=420 \
./scripts/verify_capability_deployment.sh
```

The gateway run was executed with:

```bash
ISSUE126_GATEWAY_COMPOSE_PROJECT=value-investment-agent-issue126-gateway-final \
ISSUE126_HEALTH_TIMEOUT_SECONDS=420 \
./scripts/verify_issue126_gateway.sh
```

Both runners use unique Compose project names and clean their own containers
and networks on exit. They do not run global Docker pruning or remove shared
volumes.

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
- The combined all-replica-plus-gateway run must be repeated on a Docker VM
  with sufficient memory before treating that deployment shape as a supported
  local profile. The isolated gateway and capability gates are independently
  green.
