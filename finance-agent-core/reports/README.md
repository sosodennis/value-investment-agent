# Reports Version-Control Policy

This directory stores runtime outputs from release-gate and replay workflows.
Most files are generated artifacts and should not be committed by default.

## Commit Policy

Commit only canonical release evidence files:

1. `fundamental_backtest_report_<cycle>.json`
2. `fundamental_release_gate_snapshot_<cycle>.json`
3. `forward_signal_calibration_pipeline_report_<version>.json`
4. `fundamental_cohort_stability_report_<cycle>.json`
5. `fundamental_replay_manifest_live_<cycle>.json`
6. `fundamental_replay_checks_report_live_<cycle>.json`
7. `fundamental_replay_cohort_gate_<cycle>.json`
8. `fundamental_live_replay_cohort_run_<cycle>.json`
9. `fundamental_cohort_release_checklist_<cycle>.md`
10. `fundamental_reinvestment_clamp_profile_validation_report_<cycle>.json`

Everything else under this directory is treated as local/ephemeral diagnostics.

## Why

- Keep pull requests reviewable and low-noise.
- Avoid unbounded repository growth from replay input snapshots.
- Preserve auditable release evidence for governance decisions.

## Notes

- CI always uploads runtime artifacts via GitHub Actions, even when not committed.
- Existing historical files may still be tracked from earlier commits; this policy
  prevents new noise from being added.
