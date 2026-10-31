# Issue 194 acceptance evidence

Verification target: `67a5b913705bda8b93ab3835c0439fe2b7dbda98`, branch
`codex/issue-194-safe-key-rotation`, based on `origin/main` at #193.

The implementation makes the provider service own key-scoped rotation,
shared key health, and the total retry budget. Only an explicit
`openrouter_key_limit` or credential authentication failure can rotate a key.
Model, account, workspace, and upstream-provider limits stay on the current
key; retryable limits honor `Retry-After` inside the original deadline.

## Verification performed

- `llm-provider-service/.venv/bin/pytest -q`: 59 passed, 5 skipped. The
  skipped tests require the optional PostgreSQL integration database.
- With the existing disposable local test database on port `55492`,
  `POSTGRES_HOST=127.0.0.1 POSTGRES_PORT=55492 POSTGRES_DB=langgraph
  POSTGRES_USER=postgres POSTGRES_PASSWORD=postgres
  RUN_LLM_PROVIDER_POSTGRES_TESTS=1 ./.venv/bin/pytest -q
  tests/test_key_import_postgres.py tests/test_replacement_lock_postgres.py`:
  5 passed.
- `llm-provider-service/.venv/bin/ruff check src tests` and
  `llm-provider-service/.venv/bin/ruff format --check src tests`: passed.
- `uv run --project finance-agent-core pytest -q
  finance-agent-core/tests/test_llm_settings_api.py
  finance-agent-core/tests/test_llm_provider_remote_client.py`: 21 passed.
- `frontend/npm test -- --run`: 239 passed across 45 files.
- `frontend/npm run typecheck`, the scoped LLM Settings ESLint check, and
  `frontend/npm run build`: passed.
- `bash scripts/generate-contracts.sh`: passed with no generated contract
  drift.

The focused fault-injection tests cover key-scoped 429 rotation, global 429
same-key retry, 401 key classification, 402 credit categories, 5xx and
timeout normalization, zero and HTTP-date `Retry-After`, one shared attempt
budget, stale success events, cooldown expiry, tenant filtering, streaming
interruption without replay, and Redis write failure without request replay.

## Two-replica Compose check

The isolated project was `value-investment-agent-issue-194`. The verification
overlay removed published ports and used tmpfs for the disposable PostgreSQL
and Redis state. `docker compose ... config --quiet` passed, the provider image
built successfully, and
`docker compose -p value-investment-agent-issue-194 ... up -d --scale
llm-provider-service=2 postgres redis llm-provider-service` started two healthy
provider replicas plus healthy PostgreSQL and Redis containers.

Both provider containers returned `{"status":"ready","contract_version":"internal.v1"}`
from `/readyz`. A health record written through the provider telemetry adapter
in replica 1 was read in replica 2 with `status='cooldown'`, a bounded expiry,
`failure_count=1`, and the safe `rate_limited` category. The synthetic UUID
record was deleted, and the Compose project was stopped with `docker compose
-p value-investment-agent-issue-194 ... down`; no volume data was removed.

## Limits and remaining gates

- No live OpenRouter inference or real upstream 429 injection was run in this
  local verification; no provider credential was used and no secret appears in
  this record.
- The two-replica check proves service readiness and shared Redis health
  propagation. It does not claim a successful real completion through both
  replicas or an OpenRouter account quota profile.
- SBOM/CVE review for the pinned LiteLLM image remains an external #189 gate.
- Redis reads fail closed for data-plane selection. Health writes are best
  effort after a successful request, so a Redis write outage does not replay or
  duplicate the upstream call.

The Fernet encryption key rotation remains out of scope and is tracked
separately from this issue.
