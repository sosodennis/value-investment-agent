# Technical Governance Report Runbook

## Goal

Generate a deterministic governance snapshot and drift report for the technical analysis calibration stack. This captures the current fusion model version, guardrail version, calibration mapping metadata, and drift vs a baseline.

## Inputs

1. Output path for report JSON (required).
2. Optional baseline JSON:
- A prior governance report JSON, or
- A registry payload JSON (same shape as `registry` in the report).
3. Optional registry output path (to persist the current registry snapshot).

## Command

Generate report + registry:

```bash
uv run --project finance-agent-core python scripts/run_technical_governance_report.py \
  --output reports/technical_governance_report.json \
  --registry-output reports/technical_governance_registry.json
```

Compare against a baseline:

```bash
uv run --project finance-agent-core python scripts/run_technical_governance_report.py \
  --output reports/technical_governance_report.json \
  --baseline reports/technical_governance_registry.json
```

Notes:
- If the baseline JSON has a top-level `registry` key, the script will use it automatically.
- Baseline load failures are recorded in `summary.issues`.

## Output (Report JSON)

Top-level fields:
- `schema_version`
- `generated_at`
- `registry` (current snapshot)
- `baseline_registry` (optional)
- `drifts[]` (list of `{ path, expected, actual }`)
- `summary` (`drift_count`, `drift_detected`, `issues[]`)

Registry fields (snapshot):
- `fusion_model_version`
- `guardrail_version`
- `calibration_mapping_version`
- `calibration_mapping_source`
- `calibration_mapping_path`
- `calibration_degraded_reason`
- `calibration_method`
- `calibration_config` (mapping bins and multipliers)

## Quality Gates (Suggested)

- `summary.drift_detected` should be `false` unless an intentional change was made.
- `summary.issues` should be empty.
- `calibration_degraded_reason` should be null/empty.

## Suggested Cadence

- Run weekly or before a release that changes calibration, fusion scoring, or guardrail rules.
- Promote a new baseline only after review and approval of the drift list.

## Rollback / Baseline Management

- If drift is unintended, revert the upstream change and re-run the report.
- Store the approved registry JSON as the new baseline for future runs.
