# Issue #327 Agent Core Fundamental Inventory

Issue: [#327](https://github.com/sosodennis/value-investment-agent/issues/327)
Branch: `codex/issue-327-legacy-cleanup`
Inventory commit: `dabc98dcf9bbd592f8720a496ac7b63002a9261d`
Legacy valuation removal checkpoint: `746acf0073579dc3e95aeccd1e4ee8f73cada9c1`

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
| Report artifact persistence | `application/workflow_orchestrator/financial_health_flow.py`, `state_updates.py`, `capabilities/artifacts_provenance/`, and `services/model_selection_artifact_service.py` | The default health flow no longer writes reports; model-selection read/write was removed in `dabc98dc`. Debate no longer loads this artifact kind; the repository is retained only for explicit artifact-contract tests and historical migration evidence. |
| Legacy valuation path | `application/workflow_orchestrator/valuation_flow.py`, `services/valuation_execution_context_service.py`, and report snapshot helpers | Removed in the next cleanup checkpoint because the default runner calls `service_valuation_flow.py`; the deleted path had no production caller. Its logging/application-service tests were deleted with it because they asserted obsolete report loading and persistence. |
| Raw report serializers and preview adapters | `interface/workflow_orchestrator/serializers.py`, `preview_projection_service.py`, and report projection helpers | Retain only where a current contract test proves a caller-owned typed projection; remove report-shaped compatibility functions after callers migrate. |

## Acceptance gates still open

1. Add a repository guard proving no active Agent Core workflow imports the SEC
   acquisition or legacy report artifact reader, then prove the default graph
   cannot reach either fallback.
2. Inventory and delete or archive unowned calibration/replay outputs without
   deleting service-owned canonical evidence.
3. Add guard tests for forbidden Agent-side SEC/report imports and legacy state
   keys on the service valuation request.
4. Re-run the exact #325 workspace route against a service-backed snapshot and
   record the snapshot ID, fact IDs, manifest digest, route, viewports, and
   evidence-inspector result.

The state-contract and import-guard checkpoint is
`6ad95777c8e404bc078fb7b8d3836df2ee75ef50`. It removes the Fundamental
`financial_reports_artifact_id` state/update contract and adds an AST guard for
the production caller layers. The debate reader checkpoint is
`88d60e2c291539626e1e81b5cb9a56a813c8f9f0`; it removes the financial report
typed port and returns an explicit service-snapshot-unavailable issue.

## Evidence for this checkpoint

| Check | Result |
| --- | --- |
| `uv run pytest tests/test_error_handling_fundamental.py tests/test_fundamental_orchestrator_logging.py -q` | exit `0`; 24 passed, 4 third-party `edgar` deprecation warnings |
| `uv run ruff check ...` and `uv run ruff format --check ...` | exit `0` |
| `python3 scripts/architecture_guard.py` | exit `0`; no boundary violations |
| `git diff --check` and commit hooks | exit `0` |

The legacy valuation removal was verified at `746acf00` with:

```sh
uv run pytest tests/test_error_handling_fundamental.py tests/agents/fundamental -q
python3 scripts/architecture_guard.py
```

Results: pytest exit `0` with 43 passed and four third-party `edgar`
deprecation warnings; architecture guard exit `0`. The obsolete valuation
workflow and its report-artifact tests are deleted. The replacement service
valuation coverage remains in
`tests/agents/fundamental/test_fundamental_service_cutover.py`.

The debate-side legacy report reader removal is the next uncommitted unit. Its
focused checks passed at `88d60e2c291539626e1e81b5cb9a56a813c8f9f0`: 41 tests across debate
context/source-reader/mapper and Fundamental service cutover; Ruff check and
format; and architecture guard. A collection attempt including
`tests/test_debate_optimization.py` remains blocked by that existing test's
required `LLM_PROVIDER_SERVICE_URL` environment variable.

The focused command and result were:

```sh
uv run pytest tests/test_debate_context.py tests/test_debate_report_reader.py \
  tests/test_debate_mapper.py tests/agents/fundamental/test_fundamental_service_cutover.py -q
```

Exit `0`; 41 passed. The blocked collection command is not used as acceptance
evidence for this checkpoint.

The state/import guard command was:

```sh
uv run pytest tests/test_error_handling_fundamental.py \
  tests/test_fundamental_import_hygiene_guard.py \
  tests/agents/fundamental/test_fundamental_service_cutover.py -q
```

Exit `0`; 31 passed with four third-party `edgar` deprecation warnings.
