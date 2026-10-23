# Issue 120 Acceptance Report

## Scope

- Issue: #120, LLM Provider Service
- Base: `275035bce879dce8cd6d0e94af4c02cb2a919efc`
- Worktree branch: `codex/issue-120-llm-service`
- Result: standalone `llm-provider-service` control/data plane, typed backend client boundary, Compose wiring, and boundary tests.

## Checks

| Check | Result | Evidence |
| --- | --- | --- |
| Service lint and formatting | PASS | `cd llm-provider-service && uv run ruff check src tests` |
| Service lint and boundary tests | PASS | `cd llm-provider-service && uv run ruff check src tests && uv run pytest tests/test_service_boundary.py -q` -> 7 passed |
| Backend provider tests | PASS | `cd finance-agent-core && uv run ruff check src/llm_provider/infrastructure/remote_client.py tests/test_llm_provider_remote_client.py && uv run pytest tests/test_llm_provider_remote_client.py tests/test_llm_provider_contract.py tests/test_llm_provider_lifecycle.py tests/test_llm_settings_api.py tests/test_litellm_gateway_provider.py tests/test_litellm_gateway_streaming.py tests/test_litellm_admin.py -q` -> 76 passed |
| Compose default configuration | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose -p value-investment-agent-issue120 config --quiet` |
| Compose gateway profile | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose --profile llm-gateway -p value-investment-agent-issue120 config --quiet` |
| Inference named-context build checks | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose build --check model-inference-news model-inference-fls` -> both checks completed with no warnings |
| Provider container build | PASS | `LITELLM_MASTER_KEY=compose-validation-only docker compose build llm-provider-service` |
| Architecture boundaries | PASS | `python3 scripts/architecture_guard.py` |
| Patch whitespace | PASS | `git diff --check` |

## Remaining issues

- The service startup migration reads legacy ownership/settings tables when present. This preserves existing deployments but should be removed after a separately managed data migration is complete.
- `/readyz` verifies local initialization and internal authentication configuration; it does not probe LiteLLM admin connectivity. Gateway failures are surfaced through provider operation errors.
- Live Postgres, Redis, LiteLLM, and OpenRouter integration was not run in this isolated acceptance pass.
- The service image was built; no live Postgres, Redis, LiteLLM, or OpenRouter integration was run.

## Delegation note

The first architecture review was accidentally delegated with `gpt-6-sol` rather than the requested `gpt-6.1-sol`. The corrected review used `gpt-6.1-sol` with the requested reasoning level; no implementation decision depends solely on the first review.
