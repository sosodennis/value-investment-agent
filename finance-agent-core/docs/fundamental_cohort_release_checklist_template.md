# Fundamental Cohort Release Checklist Template

Use this template for each profile/calibration release candidate.

## Release Metadata

- Date:
- Owner:
- Candidate artifact version:
- Mapping/profile path:
- Backtest report path:
- Replay report path (required for cohort release):

## Cohort Scope

- Tickers:
- Cohort case count target:
- Consensus coverage minimum:

## Gate Configuration (record actual values)

- `max_consensus_gap_median_abs`:
- `max_consensus_gap_p90_abs`:
- `min_consensus_gap_count`:
- `max_consensus_degraded_rate`:
- `min_consensus_confidence_weight`:
- `min_consensus_quality_count`:
- `min_replay_trace_contract_pass_rate`:
- `max_replay_quality_block_rate`:
- `min_replay_cache_hit_rate`:
- `max_replay_warm_latency_p90_ms`:
- `max_replay_cold_latency_p90_ms`:

## Evidence Snapshot

- `summary.total_cases`:
- `summary.ok`:
- `summary.errors`:
- `summary.consensus_gap_distribution.available_count`:
- `summary.consensus_gap_distribution.median`:
- `summary.consensus_gap_distribution.p90_abs`:
- `summary.consensus_degraded_rate`:
- `summary.consensus_confidence_weight_avg`:
- `summary.shares_scope_mismatch_rate`:
- `summary.guardrail_hit_rate`:
- `summary.replay_checks.total_cases`:
- `summary.replay_checks.passed_cases`:
- `summary.replay_checks.failed_cases`:
- `summary.replay_checks.trace_contract_pass_rate`:
- `summary.replay_checks.quality_block_rate`:
- `summary.replay_checks.cache_hit_rate`:
- `summary.replay_checks.warm_latency_p90_ms`:
- `summary.replay_checks.cold_latency_p90_ms`:
- `gate_error_codes` (from release-gate stderr/snapshot):

## Governance Checks

1. Single-source consensus degraded path observed and not treated as high confidence.
- Result:
- Evidence:

2. Canonical market datum normalization present (`target_mean_price.horizon=12m`, `shares_outstanding.shares_scope` present).
- Result:
- Evidence:

3. Replay trace contract gate satisfied (`trace_contract_pass_rate >= min_replay_trace_contract_pass_rate`).
- Result:
- Evidence:

4. Release gate exit code:
- Result:
- Evidence:

## Decision

- Release decision: `Approve` / `Reject`
- Reason:
- Rollback artifact (if reject or fallback required):
- Follow-up actions:
