## Summary
- [ ] Explain what changed.
- [ ] Explain why this change is needed.

## Scope
- [ ] This PR follows the backend guideline: `finance-agent-core/docs/development_guidelines.md`.
- [ ] Any out-of-scope changes are explicitly listed.

## Architecture / Contracts
- [ ] Boundary logic remains in boundary layers (`api`, `interface/adapters`, persistence serialization).
- [ ] Core logic (`workflow/state`, `workflow/nodes`, `interface/mappers`) uses canonical typed payloads only.
- [ ] No compatibility fallback branches were introduced.
- [ ] Frontend protocol/types updated if backend contract changed.
- [ ] Frontend API boundary decoding is parser-first (no direct `as` cast from `fetch(...).json()` payloads).
- [ ] Frontend SSE boundary decoding is parser-first (`parseAgentEvent(...)` used before reducer/event consumption).
- [ ] Frontend artifact boundary decoding is parser-first (`useArtifact` call sites provide explicit parser).
- [ ] Frontend preview consumption is parser-first (no `as FinancialReport[]` or equivalent raw preview assertions in UI paths).
- [ ] New/changed preview output uses dedicated parser module (`frontend/src/types/agents/<domain>-preview-parser.ts`).
- [ ] New/changed output wiring updates `frontend/src/types/agents/output-adapter.ts` (parser/adapter/view-model boundary remains centralized).

## Typing Rules
- [ ] No `Any` introduced in `finance-agent-core/src` or `finance-agent-core/api`.
- [ ] No `hasattr(...)`-based duck typing introduced in core logic.
- [ ] New/changed function signatures have explicit types.
- [ ] Frontend `npm run typecheck` passed.

## Artifact / State Rules
- [ ] State `artifact` fields use canonical dict payloads.
- [ ] `build_artifact_payload(...)` is used when emitting agent artifacts.
- [ ] No Pydantic model objects are stored directly in workflow state.

## Provenance Imports
- [ ] `ComputedProvenance`, `ManualProvenance`, `XBRLProvenance`, `TraceableField` are imported from `src/common/traceable.py`.

## Validation
- [ ] Lint passed (`uv run ruff check ...`).
- [ ] Forbidden patterns check passed (`rg -n "\bAny\b|hasattr\(" src api`).
- [ ] Relevant tests passed (`uv run pytest ...`).
- [ ] Frontend lint/test/typecheck passed (`npm run lint && npm run typecheck && npm run test -- --run`).
- [ ] Frontend parser tests passed (contract and preview parser suites).
- [ ] Contract artifacts re-generated and committed (`bash scripts/generate-contracts.sh`).
- [ ] Monorepo contract gates workflow passed.

## Protocol Migration (If introducing new SSE protocol version, e.g. `v2`)
- [ ] `contracts/fixtures/manifest.json` updated (`supported_versions` reflects the new canonical version set).
- [ ] New version fixture added (or updated) under `contracts/fixtures/`.
- [ ] Fixture validator passed (`python3 scripts/validate-sse-fixtures.py`).
- [ ] Backend fixture tests updated/passed for the new canonical version.
- [ ] Frontend fixture tests updated/passed for the new canonical version.
- [ ] Old protocol version removed from runtime support in the same PR (zero-compat policy).

## Docs
- [ ] Documentation updated if contracts or behavior changed.
