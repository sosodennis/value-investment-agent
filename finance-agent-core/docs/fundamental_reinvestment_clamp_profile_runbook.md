# Fundamental Reinvestment Clamp Profile Runbook

## Purpose
- Produce a versioned clamp profile artifact for `dcf_growth` severe harmonized-mismatch path.
- Keep updates auditable and bi-weekly, without editing code constants.

## Input Contract
- Schema: `fundamental_reinvestment_clamp_profile_input_v1`
- Required fields:
  - `schema_version`
  - `profile_version`
  - `as_of_date`
  - `dcf_growth.severe_scope_mismatch_ratio_threshold`
  - `dcf_growth.severe_mismatch_capex_terminal_lower_min`
  - `dcf_growth.severe_mismatch_capex_terminal_lower_year1_ratio`
  - `dcf_growth.severe_mismatch_wc_terminal_lower_min`
  - `dcf_growth.severe_mismatch_wc_terminal_lower_year1_ratio`
- Optional:
  - `evidence_refs` (list of URLs)

## Build Command
```bash
uv run --project finance-agent-core python finance-agent-core/scripts/build_fundamental_reinvestment_clamp_profile.py \
  --input /tmp/reinvestment_clamp_profile_input.json \
  --output finance-agent-core/reports/reinvestment_clamp_profile_v1_2026-03-10.json
```

## Runtime Wiring
- Env override:
  - `FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH=/abs/path/to/profile.json`
- If env path is absent, runtime uses default artifact:
  - `src/agents/fundamental/domain/valuation/parameterization/config/reinvestment_clamp_profile.default.json`
- If load/parse fails, runtime falls back to embedded default and writes degraded reason in assumptions.

## Release Gate Wiring
- Release gate script validates the profile artifact before final pass:
  - script: `finance-agent-core/scripts/run_fundamental_release_gate.sh`
  - validator: `finance-agent-core/scripts/validate_fundamental_reinvestment_clamp_profile.py`
  - failure exit code: `9`
- Relevant env vars:
  - `FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_PATH`
  - `FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MAX_AGE_DAYS`
  - `FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_MIN_EVIDENCE_REFS`
  - `FUNDAMENTAL_REINVESTMENT_CLAMP_PROFILE_VALIDATION_REPORT_PATH`

## Validation Checklist
1. Run targeted tests:
```bash
uv run --project finance-agent-core python -m pytest \
  finance-agent-core/tests/test_reinvestment_clamp_profile_service.py \
  finance-agent-core/tests/test_build_fundamental_reinvestment_clamp_profile_script.py \
  finance-agent-core/tests/test_param_builder_canonical_reports.py -q
```
2. Confirm replay assumptions contain:
- `reinvestment_clamp_profile loaded (...)` or fallback reason
- severe-floor statement with `profile_version=...`
3. Keep bi-weekly profile artifacts under `finance-agent-core/reports/`.
