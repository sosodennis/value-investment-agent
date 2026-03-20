# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement the phase-1 registry backbone for technical decision observability.
- Add the schema, ports, runtime wiring, and degraded failure handling needed to persist append-only prediction events after successful technical finalization.
- Keep artifact persistence and observability persistence as separate responsibilities.

## Non-Goals

- Implement delayed labeling.
- Implement monitoring read models.
- Modify calibration fitting logic.

## Constraints

- New capability stays under `technical/subdomains/decision_observability`.
- Preserve DB foreign keys where they protect correctness.
- Use fixed horizons `1d`, `5d`, `20d`.
- Event writes are degraded but non-fatal in phase 1.
- Do not mix observability methods into `ITechnicalArtifactRepository`.

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

- Registry ORM tables and migration plan
- Observability application port and runtime injection point
- Event registry mapping and write path
- Integration and degraded-path test coverage

## Done-When

- [ ] Every successful semantic translate flow writes a prediction event after report artifact persistence
- [ ] Event-write failures are logged and do not block final report delivery
- [ ] Schema and ports match the accepted ADR
- [ ] Tests and changed-path lint pass

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q && \
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical finance-agent-core/src/infrastructure
```
