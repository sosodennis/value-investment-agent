# Fundamental P2 Conservative Path Replay Remediation Plan (2026-03-08)

## Requirement Breakdown

1. Objective
- Reduce systematic undervaluation caused by conservative P2 assumption path in DCF variants.
- Enable reproducible, contract-first replay tuning without brittle dependency on raw log parsing.
- Keep valuation formula graph unchanged; improve assumption-path governance and replay operability.

2. Success Criteria
- Replay accepts structured input contract with explicit override payload and staleness mode selection.
- Same replay case can produce baseline vs tuned drift report with explainable key deltas:
  `intrinsic/p50/p95/wacc/terminal_growth/raw->guarded path`.
- P2 path controls can be tuned and audited without code edits (configuration/input driven).

3. Constraints
- Direct rollout (no feature flag).
- Preserve deterministic fallback behavior.
- No front-end interaction redesign in this iteration.

4. Out of Scope (This Iteration)
- No new paid external data provider integration.
- No full policy retraining pipeline changes.
- No DCF core formula graph rewrite.
- No online auto-retuning loop.

## Technical Objectives and Strategy

1. Replay Contract Hardening
- Upgrade replay input to `valuation_replay_input_v2` with explicit, typed override surface.
- Keep parser strict (`extra=forbid`) to avoid hidden/fragile knobs.

2. Replay Execution Overrides
- Add optional `--override-json` path to replay CLI.
- Apply deterministic deep-merge of override onto replay payload before param build.
- Add `staleness_mode` selector:
  - `snapshot`: use staleness metadata from input as-is.
  - `recompute`: recompute staleness from `market_datums` and as-of timestamps.

3. Conservative Path Observability
- Extend replay report fields to include override/staleness execution metadata.
- Ensure metadata is machine-readable for gate scripts and cohort replay analysis.

4. Maintainability Principle
- Centralize tuning entry points in contract + replay script; avoid ad-hoc env-only tuning paths.
- Prefer small, typed, test-backed extension over cross-module large rewrites.

## Involved Files

1. Contract and replay execution
- `finance-agent-core/src/agents/fundamental/interface/replay_contracts.py`
- `finance-agent-core/scripts/replay_fundamental_valuation.py`

2. Replay docs/tests
- `finance-agent-core/docs/fundamental_replay_input_contract.md`
- `finance-agent-core/tests/test_replay_fundamental_valuation_script.py`

3. Optional follow-up (next slice)
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py`
  (extract/share staleness recompute utility if replay-side implementation proves reusable)

## Detailed Per-File Plan

1. `replay_contracts.py`
- Introduce v2 schema with typed optional fields:
  - `staleness_mode`: `snapshot|recompute`
  - `override`: object payload for deterministic override merge
- Keep strict validation and non-empty checks for `model_type` and `reports`.

2. `replay_fundamental_valuation.py`
- Parse new `--override-json` argument.
- Merge `--override-json` with contract-level override deterministically.
- Apply staleness mode before `build_params`:
  - In `snapshot` mode: pass-through.
  - In `recompute` mode: recompute `market_datums[*].staleness` and top-level stale helper fields.
- Extend report with:
  - `replay_staleness_mode`
  - `override_applied`
  - `override_keys`

3. `test_replay_fundamental_valuation_script.py`
- Add tests for:
  - v2 contract parse success/failure.
  - override merge behavior.
  - staleness recompute mode metadata/report behavior.

4. `fundamental_replay_input_contract.md`
- Document v2 schema and CLI usage examples.
- Clarify migration guidance from v1 to v2.

## Risk/Dependency Assessment

1. Functional Risk
- Recompute mode may produce drift vs historical baseline.
- Mitigation: explicit mode selection and mode label in report.

2. Contract Migration Risk
- Existing v1 fixtures/scripts may fail if strict cutover is immediate.
- Mitigation: migrate fixtures and gate scripts in same change set; keep clear error codes.

3. Governance Risk
- Override surface could become uncontrolled if not typed.
- Mitigation: contract-level strict typing + explicit override key logging.

4. Dependency
- Replay correctness depends on complete `market_datums` payload quality.
- Mitigation: fallback to snapshot mode when recompute prerequisites are missing.

## Validation and Rollout Gates

1. Gate 1: Contract
- `valuation_replay_input_v2` validation passes.
- Invalid schema returns machine-readable error code.

2. Gate 2: Replay behavior
- Baseline replay in `snapshot` mode remains deterministic within tolerance.
- `recompute` mode changes are explainable and surfaced in report fields.

3. Gate 3: Regression
- Existing replay script tests pass after migration.
- New tests for override/staleness mode pass.

4. Gate 4: Operational readiness
- Docs updated with v2 examples.
- Replay consumers can produce inputs without log-text coupling.

## Assumptions/Open Questions

1. Confirmed: No backward compatibility requirement for old payload shape.
2. Confirmed: This iteration is backend + replay contract/report only.
3. Resolved: staleness recompute utility extracted to market-data module.
4. Open: whether guardrail profile tuning should be contract-driven in same iteration or next iteration.

## Maintainability Impact and Worthiness Assessment

1. Maintainability Benefits
- Stronger replay contract removes hidden dependency on log format and ad-hoc parsing.
- Reproducible replay tuning path lowers manual debugging cost and improves auditability.
- Structured override inputs enable deterministic experimentation and easier CI integration.

2. Maintainability Costs
- Additional schema/version and test maintenance.
- Slightly larger replay script surface area.

3. Net Decision
- Worth implementing now.
- Reason: current tuning workflow is bottlenecked by fragile inputs and unclear assumption-path control; contract-first replay materially improves engineering throughput and governance quality.

## Execution Progress (As of 2026-03-08)

Completed slices:
1. Replay contract upgraded to `valuation_replay_input_v2` with strict schema, `staleness_mode`, `override`.
2. Replay CLI supports `--override-json` with deterministic deep-merge.
3. Replay report includes override/staleness execution fields.
4. Staleness recompute logic centralized in market-data module and reused by replay.
5. Terminal-growth stale fallback policy is configurable:
   `default_only` vs `filing_first_then_default`.
6. Replay report includes terminal-growth path diagnostics:
   fallback mode and anchor source.
7. Terminal-growth path summary now writes into `build_result.metadata` as
   structured fields under:
   - `data_freshness.terminal_growth_path`
   - `parameter_source_summary.terminal_growth_path`
8. Replay report extraction now prefers metadata-path terminal-growth fields;
   assumptions parsing remains fallback-only.
9. Regression coverage added for terminal-growth metadata path in parameterization
   and replay script tests.
10. Release-gate replay checks now hard-fail when replay output misses terminal-growth
    path fields (`error_code=terminal_growth_path_missing`), with docs/tests updated.

Remaining slices (unfinished):
1. None.
