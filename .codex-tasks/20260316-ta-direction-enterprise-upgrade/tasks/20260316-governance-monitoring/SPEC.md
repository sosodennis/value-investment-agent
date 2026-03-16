# Task Specification

## Goal

Deliver governance + monitoring artifacts for Technical Direction calibration, including a registry snapshot and drift-aware validation report.

## Non-Goals

- No production scheduler wiring.
- No UI changes.
- No changes to fundamental agent code.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Domain logic must remain deterministic.
- Avoid heavy runtime changes; produce offline artifacts via script.

## Acceptance Criteria

- Governance registry snapshot can be generated from current calibration + model versions.
- Validation report includes drift detection vs baseline registry.
- Report exposes summary fields (`drift_count`, `drift_detected`, `issues`).
- Validation gates pass.

## Validation

- `rg "governance" finance-agent-core/src/agents/technical -n`
- `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/technical/subdomains/governance finance-agent-core/scripts/run_technical_governance_report.py`
