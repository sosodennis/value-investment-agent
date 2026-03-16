# Task Specification

## Goal

Produce an alignment specification that maps the planned Technical calibration pipeline to the existing Fundamental forward-signal calibration pattern, without modifying fundamental code.

## Non-Goals

- No code changes in `finance-agent-core/src/agents/fundamental/`.
- No implementation of the technical pipeline in this task.
- No changes to runtime orchestration.

## Constraints

- Preserve current agent topology (`application/domain/interface/subdomains`).
- Alignment must be contract-level (artifacts, configs, metadata, IO patterns), not copy-paste of implementation.
- Deliverable is documentation only.

## Acceptance Criteria

- Alignment spec document exists at:
  - `docs/reports/technical-calibration-alignment-spec.md`
- Document explicitly maps:
  - contracts (observation, fit report, config)
  - IO (load/write; env var override; default fallback)
  - metadata fields (mapping_source/path/degraded_reason)
  - where runtime should consume calibration output
- Document lists out-of-scope items and risks.

## Validation

- `test -f docs/reports/technical-calibration-alignment-spec.md`
