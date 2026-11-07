# Issue #327 Agent Core Ownership Audit

Issue: [#327](https://github.com/sosodennis/value-investment-agent/issues/327)
Branch: `codex/issue-327-legacy-cleanup`
Base under audit: `9c70bf0da054f528661c7b501e627e0a22aaa3c0`

## Baseline

The current branch passes the architecture guard and the focused Fundamental
Agent suite before cleanup:

```sh
python3 scripts/architecture_guard.py
uv run --project finance-agent-core pytest -q \
  finance-agent-core/tests/agents/fundamental \
  finance-agent-core/tests/test_error_handling_fundamental.py \
  finance-agent-core/tests/test_fundamental_orchestrator_logging.py \
  finance-agent-core/tests/test_fundamental_capability_facades.py \
  finance-agent-core/tests/test_sec_xbrl_financial_payload_service.py
```

Results: architecture guard exit `0`; pytest exit `0`, `73 passed, 4
warnings in 49.84s`. The warnings are third-party `edgar` deprecation
warnings. No application failure was observed in this baseline.

## Active Legacy Path

The live ownership problem is in the default Fundamental workflow wiring:

1. `finance-agent-core/src/agents/fundamental/application/wiring.py:14-16`
   imports the Agent-owned `fetch_financial_reports_payload` facade.
2. `finance-agent-core/src/agents/fundamental/application/wiring.py:77-88`
   injects that provider into the default production runner.
3. `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:100-134`
   calls the injected provider from `run_financial_health` and parses its
   financial-report payload.
4. `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/financial_health_flow.py:53-126`
   fetches SEC/XBRL data, extracts forward signals from those reports, and
   persists a `financial_reports` artifact.
5. `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/model_selection_flow.py:107-178`
   loads that artifact for model selection; the valuation flow also carries
   `financial_reports`/`raw_financial_reports` references.

This is the path observed in the #325 live diagnostic: Agent-owned
`sec_xbrl` requests occurred before any Fundamental service business request.
The service database remained empty, so the report was not proven to use a
service-owned snapshot.

## Ownership Classification

| Area | Current classification | Decision for #327 |
| --- | --- | --- |
| Fundamental service client and typed service contracts | Agent-owned boundary adapter | Retain; this is the only runtime boundary for service operations. |
| `financial_health_flow` direct SEC/XBRL fetch and `financial_reports` artifact | Obsolete duplicate service-owned evidence path | Remove from the production runner and make the absence explicit/degraded until the service-backed request producer is available. |
| `capabilities/financial_statements/infrastructure/sec_xbrl` parser and fetcher | Legacy Agent-owned SEC implementation | Quarantine behind tests during migration; remove active imports and fallback entrypoints first, then delete only after replacement evidence is checked in. |
| Artifact repository `financial_reports` persistence | Legacy report artifact store | Retain only for migration tests until service facts replace its callers; remove active workflow writes/readers with their callers. |
| Service valuation flow, trace and immutable snapshot fields | Service-owned contract projection | Retain and strengthen boundary tests; it is the replacement path. |
| Core valuation domain calculators and typed caller assumptions | Agent-owned deterministic projection/caller inputs | Retain; no formula or policy ownership change. |
| Calibration/replay reports and fixtures | Mixed: active regression evidence versus obsolete generated output | Inventory each class before deletion; do not delete canonical service calibration or retained audit evidence. |

## Dependency and Acceptance Gap

Issue #336's issuer resolver is on `main` through PR #337, but the current
workspace run still sends only `message` unless a caller supplies a complete
`valuation_request` (`analysis_runtime/interface/routes.py:70-75` and
`analysis_runtime/infrastructure/langgraph_runner.py:308-319`). Therefore this
checkpoint does not claim #325 acceptance: a service-backed snapshot, matching
fact IDs/digest, live evidence inspector, and desktop/mobile route evidence
remain unverified. The legacy SEC path must be removed in its owning layer
without pretending that a missing request is a verified valuation.

## Next Checkpoint

Remove the default runner's direct `fetch_financial_reports_payload` injection,
replace the financial-health behavior with a typed service-boundary/degraded
outcome, migrate affected tests to assert no Agent-owned SEC fetch, and commit
that focused change before broader artifact cleanup.
