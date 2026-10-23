# Issue 120 Acceptance Report

## Scope

- Issue: #120, LLM Provider Service
- Base: `750dfb27de176865ef8a3eda8b285242c61cba52`
- Worktree branch: `codex/issue-120-llm-service`
- Implementation result before final error-boundary fixes: `aeee6dd685d7164776805dfaa49a470965b1b056`
- Result: standalone `llm-provider-service` control/data plane, typed backend client boundary, Compose wiring, deadline enforcement, and replacement serialization.

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Service lint and formatting | PASS | `cd llm-provider-service && uv run ruff check src tests` |
| Service lint, compile, strict typing, and tests | PASS | `uv run --with mypy mypy --strict --follow-imports=silent --ignore-missing-imports src/llm_provider_service/app.py`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest tests -q -rs` -> 73 passed, 1 skipped |
| Backend provider boundary tests | PASS | `uv run pytest tests/test_llm_provider_contract.py tests/test_llm_provider_lifecycle.py tests/test_llm_provider_remote_client.py tests/test_llm_provider_remote_parsing.py tests/test_llm_settings_api.py tests/test_internal_service_contracts.py -q` -> 43 passed |
| Compose default configuration | PASS | `LITELLM_MASTER_KEY=disposable-interpolation-only docker compose -p value-investment-agent-issue120-review config --quiet` |
| Compose gateway profile | PASS | `LITELLM_MASTER_KEY=disposable-interpolation-only docker compose -p value-investment-agent-issue120-review --profile llm-gateway config --quiet` |
| Inference named-context build checks | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose build --check model-inference-news model-inference-fls` -> both checks completed with no warnings |
| Provider container build | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose -p value-investment-agent-issue120-fix build llm-provider-service` |
| Architecture boundaries | PASS | `python3 scripts/architecture_guard.py` |
| Patch whitespace | PASS | `git diff --check` |

## Remaining issues

- The service startup migration reads legacy ownership/settings tables when present. This preserves existing deployments but should be removed after a separately managed data migration is complete.
- `/readyz` verifies local initialization and internal authentication configuration; it does not probe LiteLLM admin connectivity. Gateway failures are surfaced through provider operation errors.
- The PostgreSQL replacement-lock integration test passed against an isolated Compose PostgreSQL instance; the default service test run skips this opt-in test.
- A full live Redis, LiteLLM, and OpenRouter stack integration was not run in this isolated acceptance pass.

## Fix round

- Removed backend direct LiteLLM/OpenRouter fallback; provider operations now require the internal provider service client and explicit service URL/token.
- Wrapped provider-key and settings operations in deadline-scoped timeouts.
- Added a PostgreSQL advisory lock and lifecycle guard so concurrent replacement of one old key has a single winner across replicas.
- Switched the provider image to a service-local build context and removed the internal gateway narration comment.
- Kept maintenance task ownership in the provider service ASGI lifespan, added cleanup for partial runtime startup failures, and limited lifecycle failure logs to exception types.
- Added an ASGI lifespan test proving partial startup failure closes the provider runtime.
- Integrated PR head after fixes: `205a700` (full SHA recorded in Git history).
- Malformed JSON, SSE frames, and provider response schemas map to typed safe errors; `deadline_exceeded` maps to `UPSTREAM_TIMEOUT` at the backend boundary.
- Streaming deadline errors preserve their deadline classification, and async cancellation still propagates.
- Service app boundaries are strictly typed without `Any`.

## Final independent acceptance

- The original PR head `aeee6dd685d7164776805dfaa49a470965b1b056` failed independent acceptance because malformed responses escaped raw parsing errors, deadline semantics were lost, and service typing violated the project rule.
- Those findings were fixed in commits `1378365` and `2847d44`, then integrated into the PR branch.
- The isolated PostgreSQL replacement-lock test passed with `RUN_LLM_PROVIDER_POSTGRES_TESTS=1` against a disposable database.
- A live Redis, LiteLLM, and OpenRouter integration was not run. This remains an explicit deployment verification gap.

## Delegation note

The first architecture review was accidentally delegated with `gpt-6-sol` rather than the requested `gpt-6.1-sol`. The corrected review used `gpt-6.1-sol` with the requested reasoning level; no implementation decision depends solely on the first review. The cross-judge selected the existing ASGI lifespan ownership (rather than moving the maintenance task into `ProviderRuntime`) and required partial-startup cleanup plus sanitized exception-type logging; both changes are included above.
