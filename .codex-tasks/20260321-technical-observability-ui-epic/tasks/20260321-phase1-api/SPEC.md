# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Add stable backend API contracts and routes for the new Technical Observability page.
- Adapt data from the existing decision observability runtime into page-friendly response shapes.
- Keep the UI boundary independent from ORM and raw repository semantics.

## Non-Goals

- Build the frontend route or page shell.
- Add public or external dashboard APIs.
- Redesign the underlying decision observability truth model.

## Constraints

- Responses must come from DB-backed observability read models.
- API responses must keep `raw outcomes` and `approved label snapshots` distinguishable.
- Contracts should be stable enough for generated frontend type sync.

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

- Observability summary and aggregate API models
- Event list and event detail API models
- Calibration readiness API models
- FastAPI routes and focused backend tests

## Done-When

- [ ] The backend exposes dedicated observability UI endpoints
- [ ] Frontend contract generation has a stable target
- [ ] Responses avoid leaking storage-only implementation details
- [ ] Tests and changed-path lint pass

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q && \
uv run --project finance-agent-core python -m ruff check finance-agent-core/api/server.py finance-agent-core/src/agents/technical/subdomains/decision_observability
```
