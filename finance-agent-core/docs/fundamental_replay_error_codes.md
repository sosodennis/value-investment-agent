# Fundamental Replay Error Codes

Scope: `finance-agent-core/scripts/replay_fundamental_valuation.py`

This document defines machine-readable `error_code` values emitted by replay failures.

## Error Codes

1. `replay_input_file_not_found`
- Trigger: provided `--input` path does not exist.

2. `replay_input_invalid_json`
- Trigger: input file is not valid JSON.

3. `invalid_replay_input_schema`
- Trigger: input JSON violates `valuation_replay_input_v2` schema.

4. `replay_override_file_not_found`
- Trigger: provided `--override-json` path does not exist.

5. `replay_override_invalid_json`
- Trigger: override file is not valid JSON.

6. `replay_override_invalid_schema`
- Trigger: override payload is not a JSON object or fails replay schema after merge.

7. `payload_contract_invalid`
- Trigger: replay payload contract is invalid after schema parse (defensive check path).

8. `param_build_missing_inputs`
- Trigger: replay parameter builder returns non-empty `missing` inputs.

9. `legacy_payload_not_supported`
- Trigger: `forward_signal.calibration_applied` or `forward_signal.mapping_version` missing/invalid.

10. `replay_output_invalid`
- Trigger: replay params dump cannot serialize to a JSON object.

11. `replay_runtime_error`
- Trigger: any unclassified runtime exception reaches top-level `main()` handler.

## Replay Checks Script Error Codes

Scope: `finance-agent-core/scripts/run_fundamental_replay_checks.py`

1. `manifest_file_not_found`
- Trigger: `--manifest` path does not exist.

2. `manifest_invalid_json`
- Trigger: manifest file is not valid JSON.

3. `manifest_invalid_schema`
- Trigger: manifest violates `valuation_replay_manifest_v1` schema.

4. `replay_runtime_error`
- Trigger: unclassified runtime exception in replay checks runner.

5. `terminal_growth_path_missing`
- Trigger: replay case returned success but missing required terminal-growth path
  fields in output (`replayed_terminal_growth_fallback_mode`,
  `replayed_terminal_growth_anchor_source`).

6. `forward_signal_trace_missing`
- Trigger: replay case returned success but missing required forward-signal trace
  fields in output (`replayed_forward_signal.calibration_applied`,
  `replayed_forward_signal.mapping_version`, raw/calibrated basis-point values,
  and `calibration_degraded_reason` key).

## Replay Trace Gate Validator Error Codes

Scope: `finance-agent-core/scripts/validate_fundamental_replay_trace_gate.py`

1. `replay_trace_contract_report_invalid`
- Trigger: replay checks report `summary` missing required fields.

2. `replay_trace_contract_case_count_invalid`
- Trigger: replay checks report `summary.total_cases <= 0`.

3. `replay_trace_contract_pass_rate_below_min`
- Trigger: observed trace-contract pass rate is lower than configured minimum.

## Live Replay Cohort Gate Issue Codes

Scope: `finance-agent-core/scripts/validate_fundamental_replay_cohort_gate.py`

1. `replay_report_intrinsic_delta_available_cases_missing_or_invalid`
- Trigger: replay report summary missing valid `intrinsic_delta_available_cases` while
  `--max-intrinsic-delta-p90-abs` gate is enabled.

2. `replay_report_intrinsic_delta_available_cases_empty`
- Trigger: replay report has zero intrinsic-delta coverage while intrinsic-delta gate is enabled.

3. `replay_report_intrinsic_delta_p90_abs_missing_or_invalid`
- Trigger: replay report summary missing valid `intrinsic_delta_p90_abs` while intrinsic-delta gate is enabled.

4. `replay_report_intrinsic_delta_p90_abs_above_max`
- Trigger: replay report summary `intrinsic_delta_p90_abs` exceeds configured maximum threshold.

## Integration Note

Downstream CI/automation should key on `error_code` first, then use `error` string for debugging details.
