# Technical Calibration Alignment Spec

Date: 2026-03-16

## Purpose

Align the planned Technical calibration pipeline contract with the existing Fundamental forward-signal calibration pattern. This is a contract and lifecycle alignment only. It does not modify Fundamental code and does not implement the Technical pipeline in this task.

## Scope and Constraints

- Scope: Technical calibration contract design (artifacts, configs, IO, metadata, runtime consumption).
- Out of scope: Any change under `finance-agent-core/src/agents/fundamental/`.
- Out of scope: Runtime scheduling, production automation, or backfill execution.

## Fundamental Reference Pattern (Source of Truth)

### 1) Contracts

Reference files:
- `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/calibration/contracts.py`

Key contracts:
- `ForwardSignalCalibrationObservation`
  - `metric: str`
  - `source_type: str`
  - `raw_basis_points: float`
  - `target_basis_points: float`
- `ForwardSignalCalibrationFitReport`
  - `input_count`, `usable_count`, `dropped_count`, `min_samples_required`
  - `used_fallback`, `fallback_reason`
  - `mapping_bins_sample_count`
- `ForwardSignalCalibrationFitResult`
  - `config: ForwardSignalCalibrationConfig`
  - `report: ForwardSignalCalibrationFitReport`

### 2) Calibration Policy & Config

Reference file:
- `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/policies/forward_signal_calibration_service.py`

Key policy details:
- `ForwardSignalCalibrationConfig`
  - `mapping_version`
  - `source_multiplier`
  - `metric_multiplier`
  - `mapping_bins` (piecewise linear slopes)
- Deterministic mapping via `_piecewise_map_abs`
- Fallback to `DEFAULT_FORWARD_SIGNAL_CALIBRATION_CONFIG` when load fails

### 3) Fitting Service

Reference file:
- `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/calibration/fitting_service.py`

Key behavior:
- Uses `min_samples` threshold (default 120).
- If insufficient samples, uses fallback config + fit report with `used_fallback=True`.
- Fits mapping bins via median ratios.

### 4) IO and Artifact Storage

Reference file:
- `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/domain/calibration/io_service.py`

Key behavior:
- Load observations from JSON array or JSONL.
- Write calibration artifact as JSON with indentation.

### 5) Runtime Consumption

Reference file:
- `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_calibration_mapping_service.py`
- `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_adjustment_service.py`

Key behavior:
- Env override for mapping path: `FUNDAMENTAL_FORWARD_SIGNAL_CALIBRATION_MAPPING_PATH`.
- Default mapping path under `config/forward_signal_calibration.default.json`.
- Caches load results.
- On failure, falls back to embedded defaults with degraded reason.
- Metadata includes `mapping_source`, `mapping_path`, and `degraded_reason`.

## Technical Alignment Decisions

Technical calibration should mirror the above structure while keeping technical-specific semantics.

### A) Contracts

Create parallel contracts under:
- `finance-agent-core/src/agents/technical/subdomains/calibration/domain/contracts.py`

Proposed contracts:
- `TechnicalDirectionCalibrationObservation`
  - `timeframe: str`
  - `horizon: str`
  - `raw_score: float`
  - `direction: str` (bullish/bearish/neutral)
  - `target_outcome: float` (directional hit or signed return proxy)
- `TechnicalDirectionCalibrationFitReport`
  - Same shape as fundamental (input_count, usable_count, dropped_count, min_samples_required, used_fallback, fallback_reason)
- `TechnicalDirectionCalibrationFitResult`
  - `config` + `report`

Rationale: identical report shape enables shared governance and monitoring tooling.

### B) Calibration Config

Create parallel policy/config under:
- `finance-agent-core/src/agents/technical/subdomains/calibration/domain/policies/technical_direction_calibration_service.py`

Proposed config:
- `mapping_version: str`
- `timeframe_multiplier: dict[str, float]`
- `direction_multiplier: dict[str, float]` (optional)
- `mapping_bins` or `sigmoid_params` (depending on chosen calibration method)

Decision: if we adopt sigmoid (Platt) for small-sample stability, store `sigmoid_a`, `sigmoid_b` and a `calibration_method` field; still expose the same metadata envelope.

### C) IO Pattern

Create parallel IO service under:
- `finance-agent-core/src/agents/technical/subdomains/calibration/domain/io_service.py`

Behavior should mirror fundamental:
- Accept JSON array or JSONL observations.
- Write JSON artifact with indentation.

### D) Runtime Mapping Load

Create technical equivalent of `forward_signal_calibration_mapping_service`:
- `TECHNICAL_DIRECTION_CALIBRATION_MAPPING_PATH` env var
- Default path: `finance-agent-core/src/agents/technical/subdomains/calibration/domain/config/technical_direction_calibration.default.json`
- Load with caching; fallback to embedded defaults with `degraded_reason`.

### E) Metadata Envelope (must align)

Calibration usage metadata should match the fundamental pattern:
- `mapping_source`
- `mapping_path`
- `degraded_reason`
- `mapping_version`
- `calibration_applied`

This ensures parity with existing valuation diagnostics and audit trail expectations.

## Integration Points (Technical)

1) Offline calibration pipeline (script)
- New script (future task): `finance-agent-core/scripts/run_technical_calibration.py`
- Output JSON artifact to a path referenced by `TECHNICAL_DIRECTION_CALIBRATION_MAPPING_PATH`.

2) Online runtime integration
- Load calibration config once per process using cached loader.
- Apply calibration only to `raw_score` output, producing `confidence_calibrated`.
- Expose both `confidence_raw` and `confidence_calibrated` in report payload.

## Non-Goals (Re-affirmed)

- Do not modify fundamental calibration code or data.
- Do not add scheduler/cron in this task.

## Risks and Mitigations

- Train/serve skew: ensure offline pipeline and runtime use the same config schema version.
- Sample size instability: prefer sigmoid for low sample counts; fall back to defaults.
- Horizon ambiguity: explicitly define `horizon` values in observations (1d/1wk/1mo) and store in config.

## Validation (for this spec)

- File exists at `docs/reports/technical-calibration-alignment-spec.md`.
- No fundamental files modified in this task.
