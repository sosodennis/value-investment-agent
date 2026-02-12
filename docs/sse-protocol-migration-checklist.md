# SSE Protocol Migration Checklist
Date: 2026-02-12

## Purpose

Provide a repeatable enterprise workflow for migrating SSE protocol versions (for example `v1` -> `v2`) with a controlled coexistence window.

## Preconditions

1. Existing version remains stable in production (`v1`).
2. Consumer-driven fixture pipeline is active.
3. Contract gates are required in CI.

## Migration Steps

1. Define new protocol envelope and payload deltas.
2. Add a draft fixture template for new version in `contracts/fixtures/` (for example `sse-events-v2.template.json`).
3. Update `contracts/fixtures/manifest.json`:
   - add new version under `planned_versions`
   - keep old version under `supported_versions`
4. Implement backend support for new version (feature flag or default switch strategy).
5. Implement frontend parsing/validation strategy for dual-version window.
6. Promote v2 fixture into `supported_versions` when both sides are ready.
7. Keep v1 and v2 together during migration window.
8. Document removal criteria/date for v1.
9. After migration window, remove v1 from `supported_versions` and archive old fixture.

## Required Validation

1. `python3 scripts/validate-sse-fixtures.py`
2. `uv run pytest tests/test_protocol.py tests/test_protocol_fixtures.py -q`
3. `npm run test -- --run` (must include `protocol.contract.test.ts`)
4. CI `Monorepo Contract Gates` pass

## Merge Gate

Do not merge migration PR unless all checklist items in `.github/pull_request_template.md` protocol migration section are checked and evidenced in PR description.
