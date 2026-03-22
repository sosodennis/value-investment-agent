# Child Progress Log

## Goal

Finish the migration by removing technical debt instead of carrying it forward.

## Current State

- Status: IN_PROGRESS
- Last Updated: 2026-03-21 23:41:02 HKT

### Slice 1 (small): Remove replay-buffer compatibility

- Deleted in-memory replay buffer usage and cleanup in server runtime.
- Stream replay relies solely on durable projection + cursor.

Validation:

- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_stream_cursor_contract.py -q`

### Slice 2 (medium): End-to-end hardening checks

- Full backend test gate now passes after core valuation script import repair and test cleanup.

Validation (pass):

- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q` (788 passed, 5 skipped)
- `cd frontend && npm run test && npm run typecheck` (pass, not rerun)

### Slice 3 (small): Docs + contract cleanup

- Updated ADRs to reflect durable architecture as current state and aligned suggested file list to actual implementation.
- Regenerated OpenAPI + frontend contract types.

Validation:

- `bash scripts/generate-contracts.sh`

### Slice 4 (small): Core valuation script import repair

- Updated scripts to use `src.agents.fundamental.subdomains.core_valuation` imports.
- Reviewed test suite for replay-buffer legacy coverage; no obsolete tests found to remove.

Validation:

- `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_build_fundamental_replay_manifest_script.py finance-agent-core/tests/test_build_fundamental_reinvestment_clamp_profile_script.py finance-agent-core/tests/test_validate_fundamental_reinvestment_clamp_profile_script.py -q`

### Slice 5 (small): Record<string, unknown> audit at durability boundary

- Standardized boundary payloads to `UnknownRecord` in protocol/interrupts/dynamic form.
- Tightened `isRecord` to exclude arrays; boundary decoders already guard arrays explicitly.

Validation:

- `rg -n "Record<string, unknown>" frontend/src finance-agent-core/src/runtime | cat`

Residual:

- Remaining `Record<string, unknown>` usages are in agent artifact parsers and technical observability UI (out of runtime durability boundary).

## Next Action

- Phase 6 complete. Decide whether to open a separate cleanup task for agent artifact parser record typing.
