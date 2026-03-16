# Task Specification

## Goal

Add a deterministic LLM guardrail that blocks or replaces interpretations that contradict the deterministic Direction signal.

## Non-Goals

- No changes to fundamental agent code.
- No prompt redesign.
- No new calibration logic.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Deterministic rules belong in domain layer; application wires logging + state.
- No compatibility shims.

## Acceptance Criteria

- Guardrail detects direction mismatches between LLM interpretation and deterministic Direction.
- On mismatch, interpretation is replaced with a deterministic fallback and marked as degraded.
- Guardrail emits structured warning log with mismatch metadata.
- Validation gates pass.

## Validation

- `rg "guardrail" finance-agent-core/src/agents/technical -n`
- `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/interpretation finance-agent-core/src/agents/technical/application/semantic_pipeline_service.py`
