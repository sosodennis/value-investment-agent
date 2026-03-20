# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Build the phase-1 monitoring read model on top of database truth.
- Expose stable internal query contracts and aggregation semantics for technical decision monitoring.
- Keep the scope limited to backend and internal analytics consumers.

## Non-Goals

- Build a frontend dashboard.
- Expose a public monitoring API.
- Redesign the prediction-event or outcome schema owned by earlier phases unless required by validation.

## Constraints

- Monitoring reads from DB truth and not manual JSON files.
- Aggregations must work by at least `timeframe`, `horizon`, and `logic_version`.
- Monitoring remains internal-only in phase 1.

## Environment

- **Project root**: `/Users/denniswong/Desktop/Project/value-investment-agent`
- **Language/runtime**: Python 3.11
- **Package manager**: `uv`
- **Test framework**: `pytest`
- **Build command**: `docker compose build backend`
- **Existing test count**: Not captured in task scaffold

## Risk Assessment

- [ ] External dependencies (APIs, services) — availability confirmed?
- [x] Breaking changes to existing code — impact assessed?
- [x] Large file generation — disk space sufficient?
- [ ] Long-running tests — timeout configured?

## Deliverables

- Monitoring query contracts
- Domain read-model service and repository queries
- Interface DTOs for internal rows and aggregates
- Query and aggregation correctness tests

## Done-When

- [ ] Monitoring consumers can query DB-backed truth without relying on JSON files
- [ ] Aggregations are correct for required dimensions
- [ ] Monitoring scope remains internal-only
- [ ] Tests and changed-path lint pass

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q && \
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical
```
