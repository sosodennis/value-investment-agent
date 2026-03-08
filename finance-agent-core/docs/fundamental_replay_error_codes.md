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

## Integration Note

Downstream CI/automation should key on `error_code` first, then use `error` string for debugging details.
