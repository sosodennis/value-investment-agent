# Progress Log

---

## Session Start

- **Date**: 2026-03-21 16:10
- **Task name**: `20260321-phase1-api`
- **Task dir**: `.codex-tasks/20260321-technical-observability-ui-epic/tasks/20260321-phase1-api/`
- **Spec**: See `SPEC.md`
- **Plan**: See `TODO.csv` (4 milestones)
- **Environment**: Python / FastAPI / pytest / ruff

---

## Context Recovery Block

- **Current milestone**: COMPLETE
- **Current status**: DONE
- **Last completed**: Post-review remediation and contract regeneration
- **Current artifact**: `.codex-tasks/20260321-technical-observability-ui-epic/tasks/20260321-phase1-api/TODO.csv`
- **Key context**: Phase 1 now exposes observability aggregates, rows, event detail, and calibration readiness through dedicated backend routes with a widened filter surface aligned to `MonitoringQueryScope`.
- **Known issues**: Repo-wide pytest is not used as the completion gate because this repo still has unrelated baseline failures outside this slice.
- **Next action**: Hand off to child #2 — Phase 2 frontend route shell navigation and shared filter workspace.

---

## Milestone 1: Initial API slice landed

- **Status**: DONE
- **Started**: 16:10
- **Completed**: 17:10
- **What was done**:
  - Added the first version of observability monitoring and calibration-readiness routes.
  - Added API-facing DTOs for monitoring rows and aggregates.
  - Added a focused backend route test file and regenerated OpenAPI/frontend contracts.
- **Key decisions**:
  - Decision: Use a cached runtime dependency for the observability service.
  - Reasoning: The runtime is lightweight and repository methods already own session lifecycle, so a single cached provider keeps the route boundary simple.
  - Alternatives considered: Per-request runtime construction was rejected as unnecessary churn for a stateless service wrapper.
- **Problems encountered**:
  - Problem: The initial implementation was reviewable and test-green, but still lacked event detail and exposed a narrower filter surface than the underlying scope contract.
  - Resolution: Opened a post-review remediation slice instead of pretending the original green checks were sufficient.
  - Retry count: 0
- **Validation**: Initial focused tests and changed-path lint passed.
- **Files changed**:
  - `finance-agent-core/api/server.py`
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/interface/contracts.py`
  - `finance-agent-core/tests/test_api_observability.py`
- **Next step**: Milestone 2 — Post-review remediation

## Milestone 2: Post-review remediation

- **Status**: DONE
- **Started**: 17:45
- **Completed**: 18:05
- **What was done**:
  - Added a typed event-detail path from repository through runtime to API route.
  - Expanded route query parameters to include `agent_sources`, `reliability_levels`, event and resolved time windows, and `labeling_method_version`.
  - Switched API imports to use the `decision_observability` subdomain facade and updated interface exports accordingly.
  - Regenerated OpenAPI and frontend generated contracts after the corrected route surface.
- **Key decisions**:
  - Decision: Add event detail as a first-class API instead of deferring it to phase 2.
  - Reasoning: The Epic and phase spec already require event drill-down, so shipping phase 1 without this route would leave the frontend blocked.
  - Alternatives considered: Letting phase 2 invent detail from row data was rejected because it would force an immediate breaking API revision.
- **Problems encountered**:
  - Problem: `ruff` failed once on import ordering after the facade import rewrite.
  - Resolution: Applied `ruff --fix` on the changed API file and re-ran the changed-path lint gate.
  - Retry count: 1
- **Validation**:
  - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_api_observability.py finance-agent-core/tests/test_technical_decision_observability_monitoring.py finance-agent-core/tests/test_technical_decision_observability_calibration_builder.py -q` -> exit 0
  - `uv run --project finance-agent-core python -m ruff check finance-agent-core/api/server.py finance-agent-core/src/agents/technical/subdomains/decision_observability finance-agent-core/tests/test_api_observability.py` -> exit 0
  - `bash scripts/generate-contracts.sh` -> exit 0
  - `cd frontend && npm run typecheck` -> exit 0
- **Files changed**:
  - `finance-agent-core/api/server.py` — widened filter surface and added event-detail route
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/contracts.py` — added event-detail contract
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/ports.py` — added event-detail repository boundary
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/decision_observability_runtime_service.py` — added event-detail runtime loader
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/repository.py` — added event-detail query and mapper
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/interface/contracts.py` — added event-detail DTO and builder
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/interface/__init__.py` — exported new API models/builders
  - `finance-agent-core/src/agents/technical/subdomains/decision_observability/__init__.py` — surfaced facade exports for API usage
  - `finance-agent-core/tests/test_api_observability.py` — added route and filter-surface coverage
  - `contracts/openapi.json` — regenerated contract
  - `frontend/src/types/generated/api-contract.ts` — regenerated frontend types
- **Next step**: Phase 1 complete
