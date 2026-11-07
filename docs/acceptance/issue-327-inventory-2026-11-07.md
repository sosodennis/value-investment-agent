# Issue #327 Agent Core Fundamental Inventory

Issue: [#327](https://github.com/sosodennis/value-investment-agent/issues/327)
Branch: `codex/issue-327-legacy-cleanup`
Inventory commit: `dabc98dcf9bbd592f8720a496ac7b63002a9261d`

## Review method

The inventory covers `finance-agent-core/src/agents/fundamental`, its
Fundamental tests and fixtures, Fundamental scripts/configuration, and
documentation or CI references. The review used these repository searches:

```sh
rg --files finance-agent-core/src/agents/fundamental
find finance-agent-core/tests -type f | rg 'fundamental|sec_xbrl|replay|calibration|release|report|artifact'
rg -n 'fundamental|SEC|sec_xbrl|financial_reports|calibration|replay|release' .github finance-agent-core docs
```

The classification below is the retention decision for Agent Core. A retained
item is not evidence that it is active production behavior; active references
are listed separately so cleanup can prove they disappear.

## Retained Agent-owned behavior

| Area | Paths | Owner and reason |
| --- | --- | --- |
| Typed Fundamental boundary | `src/agents/fundamental/application/fundamental_service_port.py`, `infrastructure/`, `interface/fundamental_service_contracts.py`, `application/workflow_orchestrator/service_valuation_flow.py` | Agent Core caller boundary. Retain the signed client, request validation, approval seam, and service response projection. |
| Caller workflow state | `src/agents/fundamental/workflow/`, `application/workflow_orchestrator/state_readers.py` | Agent-owned routing and caller assumptions. Retain only fields required by the typed service contract. Legacy report identifiers are migration debt and are not a supported service input. |
| Model selection from typed identity | `application/workflow_orchestrator/model_selection_flow.py`, `capabilities/model_selection/` | Agent-owned selection of a model from `CompanyProfile` metadata. The flow no longer loads or writes report artifacts as of `dabc98dc`. |
| Presentation and contract mappers | `interface/workflow_orchestrator/`, `workflow/nodes.py` | Agent-owned serialization and workflow output. Retain deterministic contract projections; remove report-only inputs as callers migrate. |

## Service-owned or retained evidence

| Area | Paths | Owner and reason |
| --- | --- | --- |
| Immutable service facts/releases | `fundamental-service/src/`, `fundamental-service/tests/`, and the Fundamental service contracts consumed by Agent Core | Fundamental service owns SEC acquisition, normalization, mappings, quality gates, snapshots, releases, and provenance. Do not duplicate or delete service fixtures from Agent Core as part of #327. |
| Acceptance and replay evidence | `docs/acceptance/`, `finance-agent-core/tests/fixtures/fundamental_replay_inputs/`, and explicitly named release/replay scripts | Retain only deterministic, versioned contract evidence. Generated run outputs are excluded from active discovery by `scripts/validate_reports_vcs_policy.py`; do not add machine paths or raw filing bytes. |
| Calibration and policy evidence | Service-owned calibration/release artifacts; Agent-side parameterization tests that assert caller assumptions | Retain while owner, version, input/output contract, and regression test are documented. Remove unowned duplicate outputs after the owning service evidence is identified. |

## Legacy paths to remove or quarantine

| Area | Current paths/references | Decision |
| --- | --- | --- |
| Agent SEC/XBRL acquisition | `capabilities/financial_statements/infrastructure/sec_xbrl/`, `capabilities/forward_signals/infrastructure/sec_xbrl/`, and their old provider imports | No default production wiring. Keep only for migration tests until service-backed request production and #325 evidence replace them; then delete or move to an explicit archive. |
| Report artifact persistence | `application/workflow_orchestrator/financial_health_flow.py`, `state_updates.py`, `capabilities/artifacts_provenance/`, and `services/model_selection_artifact_service.py` | Remove active writes/readers and their callers. The model-selection read/write path was removed in `dabc98dc`; the remaining health/legacy valuation references are the next cleanup units. |
| Legacy valuation path | `application/workflow_orchestrator/valuation_flow.py`, `services/valuation_execution_context_service.py`, and report snapshot helpers | Not used by the default runner, which calls `service_valuation_flow.py`. Quarantine while focused tests are migrated, then remove dead report loading/snapshot persistence. |
| Raw report serializers and preview adapters | `interface/workflow_orchestrator/serializers.py`, `preview_projection_service.py`, and report projection helpers | Retain only where a current contract test proves a caller-owned typed projection; remove report-shaped compatibility functions after callers migrate. |

## Acceptance gates still open

1. Remove the remaining active `financial_reports` writer/reader references and
   prove the default graph cannot reach Agent-owned SEC or report fallback.
2. Inventory and delete or archive unowned calibration/replay outputs without
   deleting service-owned canonical evidence.
3. Add guard tests for forbidden Agent-side SEC/report imports and legacy state
   keys on the service valuation request.
4. Re-run the exact #325 workspace route against a service-backed snapshot and
   record the snapshot ID, fact IDs, manifest digest, route, viewports, and
   evidence-inspector result.

## Evidence for this checkpoint

| Check | Result |
| --- | --- |
| `uv run pytest tests/test_error_handling_fundamental.py tests/test_fundamental_orchestrator_logging.py -q` | exit `0`; 24 passed, 4 third-party `edgar` deprecation warnings |
| `uv run ruff check ...` and `uv run ruff format --check ...` | exit `0` |
| `python3 scripts/architecture_guard.py` | exit `0`; no boundary violations |
| `git diff --check` and commit hooks | exit `0` |
