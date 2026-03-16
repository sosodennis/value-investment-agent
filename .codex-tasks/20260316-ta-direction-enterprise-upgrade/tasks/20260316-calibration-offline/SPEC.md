# Task Specification

## Goal

Implement the offline Technical Direction calibration pipeline (fit + store params), aligned to the Fundamental forward-signal calibration pattern.

## Non-Goals

- No runtime integration of calibrated confidence (handled in later subtask).
- No scheduler/cron automation.
- No changes to fundamental agent code.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Keep calibration artifacts as JSON files (not stored in artifact manager).
- Avoid adding heavy dependencies (e.g., scikit-learn) in this phase.

## Acceptance Criteria

- Technical calibration domain modules exist under `subdomains/calibration/domain`.
- Default calibration config JSON exists under `subdomains/calibration/domain/config/`.
- Offline script `scripts/run_technical_direction_calibration.py` fits and writes mapping.
- Fit report supports fallback detection and sample counts.

## Validation

- `rg "technical_direction_calibration" finance-agent-core/src/agents/technical -n`
- `test -f finance-agent-core/scripts/run_technical_direction_calibration.py`
- `test -f finance-agent-core/src/agents/technical/subdomains/calibration/domain/config/technical_direction_calibration.default.json`
