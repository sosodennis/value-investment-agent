# Issue 120 Acceptance Report

## Scope

- Issue: #120, LLM Provider Service
- Base: `275035bce879dce8cd6d0e94af4c02cb2a919efc`
- Worktree branch: `codex/issue-120-llm-service`
- Implementation result: `a54b7c601dc7441cb6bf6e834de07667e844dea5`
- Result: standalone `llm-provider-service` control/data plane, typed backend client boundary, Compose wiring, deadline enforcement, and replacement serialization.

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Service lint and formatting | PASS | `cd llm-provider-service && uv run ruff check src tests` |
| Service lint, compile, and tests | PASS | `cd llm-provider-service && uv run --group dev ruff check src tests && uv run --group dev python -m compileall -q src tests && uv run --group dev pytest tests -q` -> 11 passed, 1 skipped (PostgreSQL opt-in test) |
| Backend provider boundary tests | PASS | `cd finance-agent-core && uv run ruff check src/llm_provider/application/wiring.py src/llm_provider/composition/routes.py src/llm_provider/infrastructure/remote_client.py tests/test_llm_provider_lifecycle.py tests/test_llm_settings_api.py && uv run pytest tests/test_llm_provider_lifecycle.py tests/test_llm_settings_api.py -q` -> 6 passed |
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
- Final code result SHA: `0b526e597ed4dd8acfafecfe93450bd4cfd4164c`.

## Delegation note

The first architecture review was accidentally delegated with `gpt-6-sol` rather than the requested `gpt-6.1-sol`. The corrected review used `gpt-6.1-sol` with the requested reasoning level; no implementation decision depends solely on the first review. The cross-judge selected the existing ASGI lifespan ownership (rather than moving the maintenance task into `ProviderRuntime`) and required partial-startup cleanup plus sanitized exception-type logging; both changes are included above.
