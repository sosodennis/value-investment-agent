# Fundamental Replay Input Contract Migration Plan (2026-03-07)

## Context

- Current replay/release gate path still allows `log -> snapshot_artifact_id` resolution.
- This creates strong coupling to log format/path and weakens portability in CI and user tooling.
- Target state is a deterministic replay toolchain with explicit schema-based inputs.

## Goal

1. Remove replay dependency on log parsing.
2. Define strict replay input and manifest contracts.
3. Drive release gate and CI with manifest-based replay checks.

## Confirmed Decisions

1. Remove `--log-path/--run-id/--ticker` replay entry path.
2. Store replay fixtures in repo (`tests/fixtures`).
3. Keep replay gate failure exit code as `5`.

## Execution Slices (Consolidated)

1. `S13` (`medium`): Replay contract definition + fixtures
- Add `valuation_replay_input_v1` and `valuation_replay_manifest_v1`.
- Add CI fixtures under `tests/fixtures/fundamental_replay_inputs/`.

2. `S14` (`medium`): Replay script migration to contract input
- `replay_fundamental_valuation.py` accepts only `--input`.
- Remove log/artifact-id resolution entry path.
- Keep machine-readable `error_code` outputs.

3. `S15` (`small`): Batch replay checker
- Add `scripts/run_fundamental_replay_checks.py`.
- Manifest-driven replay execution + aggregate report.

4. `S16` (`small`): Release gate migration
- `run_fundamental_release_gate.sh` switches from `FUNDAMENTAL_REPLAY_CHECKS` to `FUNDAMENTAL_REPLAY_MANIFEST_PATH`.
- Keep replay gate exit code `5`.

5. `S17` (`small`): CI workflow + docs
- CI `fundamental-release-gate` uses manifest input.
- Summarize replay `error_code` in job summary.
- Update runbook/error-code docs.

## Execution Status

1. `S13`: Done
2. `S14`: Done
3. `S15`: Done
4. `S16`: Done
5. `S17`: Done

## Validation Targets

1. Replay script tests green (`test_replay_fundamental_valuation_script.py`).
2. Replay checks script tests green (`test_fundamental_replay_checks_script.py`).
3. Release gate tests green (`test_fundamental_release_gate_script.py`).
4. Lint/checks green for changed Python files.
5. CI workflow YAML syntax valid.

## Out of Scope

1. No changes to DCF formulas or valuation math.
2. No front-end interaction changes.
3. No calibration fitting-policy redesign in this migration.
