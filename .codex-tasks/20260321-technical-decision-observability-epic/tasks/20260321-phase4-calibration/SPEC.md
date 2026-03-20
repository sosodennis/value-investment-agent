# Task Specification

## Task Shape

- **Shape**: `single-full`

## Goals

- Build the calibration observation builder that converts prediction events plus outcome paths into the existing technical calibration contracts.
- Wire the calibration domain to consume the new observation source without moving ownership of calibration or observability boundaries.
- Keep file-based loading only as an offline or manual utility path.

## Non-Goals

- Rewrite calibration fitting logic.
- Remove every file-based calibration utility immediately.
- Build automated recalibration loops.

## Constraints

- Calibration remains the downstream consumer and does not own observability internals.
- Builder output must align with existing `TechnicalDirectionCalibrationObservation` contracts.
- File-based loading may remain for offline or manual use, but not as the mainline source.

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

- Observation builder service and contracts
- Calibration facade export updates
- Integration path from observability truth to calibration consumer
- Compatibility and regression tests

## Done-When

- [ ] Existing technical calibration consumers can load observations from the new builder
- [ ] Builder output is contract-compatible with existing calibration observation models
- [ ] File-based loading is demoted to offline or manual usage without breaking that path
- [ ] Tests and changed-path lint pass

## Final Validation Command

```bash
uv run --project finance-agent-core python -m pytest finance-agent-core/tests -q && \
uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical
```
