# Task Specification

> Scope anchor for the task. Update only when goals or constraints change, and log the reason in PROGRESS.md.

## Task Shape
<!-- single-compact | single-full | epic | batch -->

- **Shape**: single-full

## Goals
<!-- What are we building? Be specific and concrete. -->

- Replace the current free-text technical analyst prompt flow with a structured interpretation contract.
- Keep deterministic `direction`, `risk_level`, and calibrated confidence as the source of truth while making the LLM output typed, auditable, and UI-friendly.
- Surface analyst-facing fields such as stance summary, evidence summary, trigger, invalidation, and validation note in the technical output.

## Non-Goals
<!-- What are we explicitly NOT doing? Prevents scope creep. -->

- No execution-agent behavior such as broker-ready `BUY` / `SELL` order output.
- No new market data providers or new indicator calculations in this task.
- No redesign of scorecard, fusion, or verification algorithms beyond interpretation contracts and consumer rendering.

## Constraints
<!-- Tech stack, style guide, performance limits, compatibility requirements -->

- Pydantic v2 conventions only.
- Breaking changes are allowed; do not keep compatibility shims.
- Keep the current technical agent topology (`application/domain/interface/infrastructure`) intact.
- Do not expose raw chain-of-thought; use concise rationale fields instead.

## Environment
<!-- Auto-filled by agent at init time -->

- **Project root**: /Users/denniswong/Desktop/Project/value-investment-agent
- **Language/runtime**: Python + TypeScript (React)
- **Package manager**: uv (backend), npm (frontend)
- **Test framework**: pytest (backend), npm build/typecheck (frontend)
- **Build command**: `npm run build`
- **Existing test count**: n/a

## Risk Assessment
<!-- Identify potential blockers or unknowns before starting -->

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [ ] Large file generation — disk space sufficient?
- [x] Long-running tests — timeout configured?

## Deliverables
<!-- Concrete outputs: files, features, endpoints, docs -->

- Structured interpretation input/output contracts for the technical analyst flow.
- Updated technical artifact schema with typed analyst perspective data.
- Updated frontend rendering for the new analyst perspective contract.
- Validation and compliance evidence recorded in task artifacts.

## Done-When
<!-- Final acceptance criteria. The task is DONE when ALL of these pass. -->

- [ ] Backend no longer depends on raw `llm_interpretation` strings as the primary interpretation contract.
- [ ] Technical report payload contains a typed analyst perspective object with structured fields.
- [ ] Frontend renders the new analyst perspective fields without type or build failures.
- [ ] Required validation gates pass or explicit skips are logged with reason.

## Final Validation Command
<!-- Single command that validates the entire deliverable. Runs at close-out. -->

```bash
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical finance-agent-core/src/interface && npm --prefix frontend run build
```

## Demo Flow (optional)
<!-- Step-by-step instructions to demonstrate the finished product. -->

1. Run a technical analysis report for a ticker with fusion, pattern, and verification artifacts.
2. Open the Technical Intelligence output.
3. Confirm the analyst perspective section shows stance, concise rationale, evidence, trigger/invalidation, and validation-aware risk note.
