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

## Typing Rules
- [ ] No `Any` introduced in `finance-agent-core/src` or `finance-agent-core/api`.
- [ ] No `hasattr(...)`-based duck typing introduced in core logic.
- [ ] New/changed function signatures have explicit types.

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

## Docs
- [ ] Documentation updated if contracts or behavior changed.
