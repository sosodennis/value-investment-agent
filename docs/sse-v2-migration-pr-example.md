# SSE v2 Migration PR Example
Date: 2026-02-12

## Purpose

This is a copy/paste-ready Pull Request example for migrating SSE protocol from `v1` to `v2` using a coexistence window.

Use together with:

1. `docs/sse-protocol-migration-checklist.md`
2. `contracts/fixtures/manifest.json`
3. `.github/pull_request_template.md`

---

## Example PR Title

`feat(protocol): introduce SSE v2 envelope with v1 coexistence window`

## Example PR Body

### Summary

1. Added backend support for SSE `protocol_version = "v2"` while keeping `v1` active.
2. Added frontend parser support for both `v1` and `v2` during migration window.
3. Added `v2` fixture and promoted `v2` into `supported_versions` in fixture manifest.
4. Kept `v1` fixture for backward compatibility.

### Why

1. `v2` adds normalized status payload and stronger event metadata.
2. Migration window is required to avoid breaking active clients.

### Scope

1. In scope: protocol envelope, frontend event parser, fixtures, tests, CI checks.
2. Out of scope: removing `v1` support (scheduled in follow-up PR).

### Architecture / Contracts

1. Boundary schema updated in backend event protocol model.
2. Frontend protocol validator updated for dual-version acceptance.
3. Contract fixtures updated and validated via `scripts/validate-sse-fixtures.py`.

### Typing Rules

1. No `Any` added.
2. No duck-typing fallback added.
3. All new function signatures are typed.

### Artifact / State Rules

1. No direct Pydantic model persisted into workflow state.
2. Canonical payload rules unchanged.

### Protocol Migration

1. Updated `contracts/fixtures/manifest.json`:
   - `v2` moved from `planned_versions` to `supported_versions`.
   - `v1` remains in `supported_versions` during migration window.
2. Added/updated fixture file:
   - `contracts/fixtures/sse-events-v2.json`
3. Validator passed:
   - `python3 scripts/validate-sse-fixtures.py`
4. Backend fixture tests passed.
5. Frontend fixture tests passed.
6. Deprecation window:
   - `v1` planned removal target: `<YYYY-MM-DD>` in PR follow-up `#<ticket>`.

### Validation

Backend:
```bash
cd finance-agent-core
UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src/interface/protocol.py tests/test_protocol.py tests/test_protocol_fixtures.py
UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_protocol_fixtures.py -q
```

Frontend:
```bash
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
```

Contracts:
```bash
cd /Users/denniswong/Desktop/Project/value-investment-agent
bash scripts/generate-contracts.sh
python3 scripts/validate-sse-fixtures.py
```

CI:

1. `Monorepo Contract Gates` passed.
2. `contract-codegen-check` passed.

### Rollback Plan

1. If v2 client parsing fails in production, switch server default back to `v1`.
2. Keep v2 code path behind feature flag until error rate returns to baseline.
3. No data migration required.

### Audit Evidence Attached

1. Link to CI run.
2. Fixture manifest diff.
3. Protocol schema diff.
4. Test run logs.
