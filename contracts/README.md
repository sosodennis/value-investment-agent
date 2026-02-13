# Contracts

This folder contains generated cross-stack contracts used by both backend and frontend.

## Files

1. `openapi.json`: Exported from FastAPI (`finance-agent-core/api/server.py`).
2. `fixtures/sse-events-v1.json`: Shared SSE contract fixtures consumed by backend and frontend tests.
3. `fixtures/manifest.json`: Source of truth for supported SSE protocol fixture versions.

## Generate

From repository root:

```bash
bash scripts/generate-contracts.sh
```

This command will:

1. Export backend OpenAPI to `contracts/openapi.json`.
2. Generate frontend TypeScript contract types at:
   `frontend/src/types/generated/api-contract.ts` using `openapi-typescript`.

## Fixture Policy

When SSE envelope or event payload contracts change:

1. Update `fixtures/manifest.json`.
2. For a supported version, add/update a concrete fixture file (e.g., `sse-events-v1.json`).
3. Keep `protocol_version` inside each event consistent with manifest version.
4. Run validator:
   `python3 scripts/validate-sse-fixtures.py`
5. Ensure backend protocol fixture tests pass.
6. Ensure frontend protocol fixture tests pass.

## Protocol Version Policy

For future protocol version rollout:

1. Add the new version fixture to `supported_versions` only when backend and frontend are both updated in the same PR.
2. Remove old version fixture from `supported_versions` in the same breaking PR (zero-compat policy).
