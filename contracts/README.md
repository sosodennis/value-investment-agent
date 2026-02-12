# Contracts

This folder contains generated cross-stack contracts used by both backend and frontend.

## Files

1. `openapi.json`: Exported from FastAPI (`finance-agent-core/api/server.py`).
2. `fixtures/sse-events-v1.json`: Shared SSE contract fixtures consumed by backend and frontend tests.
3. `fixtures/manifest.json`: Source of truth for supported and planned SSE protocol fixture versions.
4. `fixtures/sse-events-v2.template.json`: Draft template for next protocol version.

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

## Version Coexistence Template

For future protocol rollout (v1 + v2 coexistence):

1. Keep current `v1` in `supported_versions`.
2. Add `v2` to `planned_versions` with a template fixture.
3. Once backend/frontend both support v2, promote v2 to `supported_versions` and keep v1 during migration window.

Detailed migration workflow:

1. `docs/sse-protocol-migration-checklist.md`
