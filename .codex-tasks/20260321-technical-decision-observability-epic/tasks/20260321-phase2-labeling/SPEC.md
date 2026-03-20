# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Implement delayed outcome labeling for matured technical prediction events.
- Add raw outcome calculations, repository support, worker runtime, and the single-path scheduler integration described by the ADR.
- Preserve idempotent labeling and point-in-time rules.

## Non-Goals

- Build external dashboards.
- Fit or publish new calibration mappings.
- Introduce alternate scheduler modes for compatibility.

## Constraints

- Labeling must remain asynchronous and outside the online technical workflow.
- Raw outcomes are truth; do not collapse them into canonical hit or miss columns in the base table.
- Use dedicated scheduler container plus `supercronic`; no host cron and no in-process API scheduler loop.
- Reuse the market-data provider contract with isolated cache namespace and retry policy.

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

- Raw outcome labeling rules and domain contracts
- Repository support for matured-event fetch and append-only outcome writes
- Worker entrypoint and scheduler-facing command
- Idempotency, point-in-time, and degraded-provider tests

## Done-When

- [ ] Matured events can be labeled with `forward_return`, `mfe`, `mae`, and `realized_volatility`
- [ ] Duplicate labeling runs are idempotent
- [ ] Scheduler runtime follows the ADR single-path deployment decision
- [ ] Tests and changed-path lint pass

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q && \
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical
```
