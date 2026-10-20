# Architecture Module Actions

Generated from `scripts/architecture_guard.py --write-module-report`.
Each item identifies a source module, exact import target, and first remediation action.
Resolve items within their module, then remove the matching edge from
`scripts/architecture_guard_exceptions.tsv`. CI rejects new edges, stale edges,
and exceptions without a matching action ID in this report.

Current documented findings: 126.

### [DEBATE-CORE] Module remediation

#### `src.agents.debate.application.subgraph`

- `LAYER_DIRECTION` -> `src.workflow.nodes.debate.nodes` at `finance-agent-core/src/agents/debate/application/subgraph.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.nodes.debate.subgraph_state` at `finance-agent-core/src/agents/debate/application/subgraph.py:21`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.agents.debate.domain.entities`

- `CROSS_AGENT_PRIVATE_IMPORT` -> `src.agents.fundamental.domain.shared.contracts.traceable` at `finance-agent-core/src/agents/debate/domain/entities.py:5`. Depend on the target agent entrypoint or move the stable contract to shared.

#### `src.agents.debate.domain.fact_builders`

- `CROSS_AGENT_PRIVATE_IMPORT` -> `src.agents.fundamental.domain.shared.contracts.traceable` at `finance-agent-core/src/agents/debate/domain/fact_builders.py:9`. Depend on the target agent entrypoint or move the stable contract to shared.

#### `src.agents.debate.infrastructure.artifacts.debate_source_reader_repository`

- `CROSS_AGENT_PRIVATE_IMPORT` -> `src.agents.news.interface.contracts` at `finance-agent-core/src/agents/debate/infrastructure/artifacts/debate_source_reader_repository.py:10`. Depend on the target agent entrypoint or move the stable contract to shared.


### [FUNDAMENTAL-CAP-ARTIFACTS-PROVENANCE] Module remediation

#### `src.agents.fundamental.subdomains.artifacts_provenance.infrastructure.fundamental_artifact_repository`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/infrastructure/fundamental_artifact_repository.py:5`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/infrastructure/fundamental_artifact_repository.py:8`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.parsers` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/infrastructure/fundamental_artifact_repository.py:11`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.artifacts_provenance.interface.contracts`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/interface/contracts.py:7`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.types` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/interface/contracts.py:10`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/artifacts_provenance/interface/contracts.py:13`. Expose the required contract through the capability facade.


### [FUNDAMENTAL-CAP-CORE-VALUATION] Module remediation

#### `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.forward_signal_adjustment_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.domain.policies.forward_signal_policy` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_adjustment_service.py:6`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.forward_signal_calibration_mapping_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.domain.policies.forward_signal_calibration_service` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_calibration_mapping_service.py:9`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.forward_signal_parser_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.domain.policies.forward_signal_contracts` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_parser_service.py:3`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.domain.policies.forward_signal_policy` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/domain/parameterization/forward_signal_parser_service.py:6`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.core_valuation.interface.replay_contracts`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/interface/replay_contracts.py:7`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/core_valuation/interface/replay_contracts.py:10`. Expose the required contract through the capability facade.


### [FUNDAMENTAL-CAP-FORWARD-SIGNALS] Module remediation

#### `src.agents.fundamental.subdomains.forward_signals.application.extraction_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/application/extraction_service.py:6`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.forward_signals.application.ports`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/application/ports.py:5`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl.forward_signals`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/forward_signals/infrastructure/sec_xbrl/forward_signals.py:5`. Expose the required contract through the capability facade.


### [FUNDAMENTAL-CAP-MODEL-SELECTION] Module remediation

#### `src.agents.fundamental.subdomains.model_selection.domain.model_selection`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.valuation_model` at `finance-agent-core/src/agents/fundamental/subdomains/model_selection/domain/model_selection.py:14`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.model_selection.domain.model_selection_contracts`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.valuation_model` at `finance-agent-core/src/agents/fundamental/subdomains/model_selection/domain/model_selection_contracts.py:6`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.model_selection.domain.model_selection_spec_catalog`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.valuation_model` at `finance-agent-core/src/agents/fundamental/subdomains/model_selection/domain/model_selection_spec_catalog.py:3`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.subdomains.model_selection.interface.report_projection_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/subdomains/model_selection/interface/report_projection_service.py:5`. Expose the required contract through the capability facade.


### [FUNDAMENTAL-CORE] Module remediation

#### `src.agents.fundamental.application.subgraph`

- `LAYER_DIRECTION` -> `src.workflow.nodes.fundamental_analysis.nodes` at `finance-agent-core/src/agents/fundamental/application/subgraph.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.nodes.fundamental_analysis.subgraph_state` at `finance-agent-core/src/agents/fundamental/application/subgraph.py:13`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.agents.fundamental.application.wiring`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.artifacts_provenance.infrastructure.fundamental_artifact_repository` at `finance-agent-core/src/agents/fundamental/application/wiring.py:11`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.infrastructure.sec_xbrl` at `finance-agent-core/src/agents/fundamental/application/wiring.py:14`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.application.extraction_service` at `finance-agent-core/src/agents/fundamental/application/wiring.py:17`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.infrastructure.sec_xbrl` at `finance-agent-core/src/agents/fundamental/application/wiring.py:20`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.market_data.infrastructure.factory` at `finance-agent-core/src/agents/fundamental/application/wiring.py:25`. Expose the required contract through the capability facade.
- `CROSS_AGENT_PRIVATE_IMPORT` -> `src.agents.news.infrastructure.sentiment.finbert_sentiment_provider` at `finance-agent-core/src/agents/fundamental/application/wiring.py:28`. Depend on the target agent entrypoint or move the stable contract to shared.

#### `src.agents.fundamental.application.workflow_orchestrator.factory`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:38`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.orchestrator` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:41`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.valuation_model_registry` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:44`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:47`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.parsers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:50`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:53`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.serializers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:56`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.domain.model_selection` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/factory.py:59`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.financial_health_flow`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.parsers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/financial_health_flow.py:22`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/financial_health_flow.py:25`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.serializers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/financial_health_flow.py:28`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.model_selection_flow`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.valuation_model_type_service` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/model_selection_flow.py:16`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/model_selection_flow.py:19`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.domain.entities` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/model_selection_flow.py:22`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.interface.report_projection_service` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/model_selection_flow.py:25`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.orchestrator`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/orchestrator.py:31`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/orchestrator.py:34`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.domain.entities` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/orchestrator.py:37`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.ports`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/ports.py:5`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.services.model_selection_artifact_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/model_selection_artifact_service.py:16`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.domain.entities` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/model_selection_artifact_service.py:19`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.domain.financial_health_service` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/model_selection_artifact_service.py:22`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.services.valuation_completion_fields_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_completion_fields_service.py:5`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.services.valuation_execution_context_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.parsers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_execution_context_service.py:11`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_execution_context_service.py:15`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.services.valuation_execution_result_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_execution_result_service.py:6`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.parsers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_execution_result_service.py:9`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/services/valuation_execution_result_service.py:12`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.application.workflow_orchestrator.valuation_flow`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/valuation_flow.py:26`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.core_valuation.domain.parameterization.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/valuation_flow.py:29`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/valuation_flow.py:32`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.serializers` at `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/valuation_flow.py:35`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.interface.workflow_orchestrator.preview_projection_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.model_selection.interface.report_projection_service` at `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/preview_projection_service.py:3`. Expose the required contract through the capability facade.

#### `src.agents.fundamental.interface.workflow_orchestrator.serializers`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.artifacts_provenance.interface.contracts` at `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/serializers.py:3`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/serializers.py:6`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.contracts` at `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/serializers.py:9`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.fundamental.subdomains.forward_signals.interface.serializers` at `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/serializers.py:12`. Expose the required contract through the capability facade.


### [INTENT-CORE] Module remediation

#### `src.agents.intent.application.subgraph`

- `LAYER_DIRECTION` -> `src.workflow.nodes.intent_extraction.nodes` at `finance-agent-core/src/agents/intent/application/subgraph.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.nodes.intent_extraction.subgraph_state` at `finance-agent-core/src/agents/intent/application/subgraph.py:14`. Move the dependency behind an inward-facing contract or relocate the behavior.


### [NEWS-CORE] Module remediation

#### `src.agents.news.application.subgraph`

- `LAYER_DIRECTION` -> `src.workflow.nodes.financial_news_research.nodes` at `finance-agent-core/src/agents/news/application/subgraph.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.nodes.financial_news_research.subgraph_state` at `finance-agent-core/src/agents/news/application/subgraph.py:15`. Move the dependency behind an inward-facing contract or relocate the behavior.


### [ROOT-WORKFLOW] Module remediation

#### `src.workflow.graph`

- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.debate.application.subgraph` at `finance-agent-core/src/workflow/graph.py:8`. Route root graph composition through the agent's public entrypoint.
- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.fundamental.application.subgraph` at `finance-agent-core/src/workflow/graph.py:9`. Route root graph composition through the agent's public entrypoint.
- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.intent.application.subgraph` at `finance-agent-core/src/workflow/graph.py:10`. Route root graph composition through the agent's public entrypoint.
- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.news.application.subgraph` at `finance-agent-core/src/workflow/graph.py:11`. Route root graph composition through the agent's public entrypoint.
- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.technical.application.subgraph` at `finance-agent-core/src/workflow/graph.py:12`. Route root graph composition through the agent's public entrypoint.

#### `src.workflow.interrupts`

- `ROOT_WORKFLOW_PRIVATE_IMPORT` -> `src.agents.intent.interface.contracts` at `finance-agent-core/src/workflow/interrupts.py:5`. Route root graph composition through the agent's public entrypoint.

#### `src.workflow.nodes.debate.nodes`

- `LAYER_DIRECTION` -> `src.agents.debate.application.wiring` at `finance-agent-core/src/workflow/nodes/debate/nodes.py:7`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.command_adapter` at `finance-agent-core/src/workflow/nodes/debate/nodes.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.debate.subgraph_state`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/workflow/nodes/debate/subgraph_state.py:12`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.financial_news_research.nodes`

- `LAYER_DIRECTION` -> `src.agents.news.application.wiring` at `finance-agent-core/src/workflow/nodes/financial_news_research/nodes.py:4`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.command_adapter` at `finance-agent-core/src/workflow/nodes/financial_news_research/nodes.py:5`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.financial_news_research.subgraph_state`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/workflow/nodes/financial_news_research/subgraph_state.py:12`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.fundamental_analysis.nodes`

- `LAYER_DIRECTION` -> `src.agents.fundamental.application.wiring` at `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py:4`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.command_adapter` at `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py:5`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.fundamental_analysis.subgraph_state`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/workflow/nodes/fundamental_analysis/subgraph_state.py:12`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.intent_extraction.nodes`

- `LAYER_DIRECTION` -> `src.agents.intent.application.wiring` at `finance-agent-core/src/workflow/nodes/intent_extraction/nodes.py:13`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.command_adapter` at `finance-agent-core/src/workflow/nodes/intent_extraction/nodes.py:15`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.intent_extraction.subgraph_state`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/workflow/nodes/intent_extraction/subgraph_state.py:7`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.technical_analysis.nodes`

- `LAYER_DIRECTION` -> `src.agents.technical.application.wiring` at `finance-agent-core/src/workflow/nodes/technical_analysis/nodes.py:6`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.command_adapter` at `finance-agent-core/src/workflow/nodes/technical_analysis/nodes.py:7`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.workflow.nodes.technical_analysis.subgraph_state`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/workflow/nodes/technical_analysis/subgraph_state.py:12`. Move the dependency behind an inward-facing contract or relocate the behavior.


### [SHARED-BOUNDARY] Module remediation

#### `src.interface.artifacts.artifact_contract_specs`

- `SHARED_IMPORTS_AGENT` -> `src.agents.debate.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_contract_specs.py:7`. Move the shared contract out of the agent package or invert the dependency.
- `SHARED_IMPORTS_AGENT` -> `src.agents.news.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_contract_specs.py:8`. Move the shared contract out of the agent package or invert the dependency.
- `SHARED_IMPORTS_AGENT` -> `src.agents.technical.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_contract_specs.py:9`. Move the shared contract out of the agent package or invert the dependency.

#### `src.interface.artifacts.artifact_data_models`

- `SHARED_IMPORTS_AGENT` -> `src.agents.debate.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_data_models.py:7`. Move the shared contract out of the agent package or invert the dependency.
- `SHARED_IMPORTS_AGENT` -> `src.agents.fundamental.subdomains.financial_statements.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_data_models.py:8`. Move the shared contract out of the agent package or invert the dependency.
- `SHARED_IMPORTS_AGENT` -> `src.agents.news.interface.contracts` at `finance-agent-core/src/interface/artifacts/artifact_data_models.py:11`. Move the shared contract out of the agent package or invert the dependency.


### [TECHNICAL-CAP-DECISION-OBSERVABILITY] Module remediation

#### `src.agents.technical.subdomains.decision_observability.application.ports`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/subdomains/decision_observability/application/ports.py:13`. Expose the required contract through the capability facade.

#### `src.agents.technical.subdomains.decision_observability.domain.calibration_observation_builder_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.calibration.domain.contracts` at `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/calibration_observation_builder_service.py:8`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.calibration.domain.policies.technical_direction_calibration_service` at `finance-agent-core/src/agents/technical/subdomains/decision_observability/domain/calibration_observation_builder_service.py:11`. Expose the required contract through the capability facade.

#### `src.agents.technical.subdomains.decision_observability.infrastructure.labeling_worker_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/labeling_worker_service.py:13`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.infrastructure.yahoo_ohlcv_provider` at `finance-agent-core/src/agents/technical/subdomains/decision_observability/infrastructure/labeling_worker_service.py:16`. Expose the required contract through the capability facade.


### [TECHNICAL-CAP-FEATURES] Module remediation

#### `src.agents.technical.subdomains.features`

- `CAPABILITY_CYCLE` -> `src.agents.technical.subdomains.signal_fusion` at `finance-agent-core/src/agents/technical/subdomains/features/domain/fracdiff/serialization_service.py:5`. Break the capability cycle through a stable contract or workflow orchestration.


### [TECHNICAL-CAP-INTERPRETATION] Module remediation

#### `src.agents.technical.subdomains.interpretation.domain.interpretation_guardrail_service`

- `LAYER_DIRECTION` -> `src.agents.technical.interface.contracts` at `finance-agent-core/src/agents/technical/subdomains/interpretation/domain/interpretation_guardrail_service.py:5`. Move the dependency behind an inward-facing contract or relocate the behavior.


### [TECHNICAL-CAP-REGIME] Module remediation

#### `src.agents.technical.subdomains.regime`

- `CAPABILITY_CYCLE` -> `src.agents.technical.subdomains.features` at `finance-agent-core/src/agents/technical/subdomains/regime/domain/regime_classification_service.py:9`. Break the capability cycle through a stable contract or workflow orchestration.

#### `src.agents.technical.subdomains.regime.domain.regime_classification_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.domain` at `finance-agent-core/src/agents/technical/subdomains/regime/domain/regime_classification_service.py:9`. Expose the required contract through the capability facade.


### [TECHNICAL-CAP-SIGNAL-FUSION] Module remediation

#### `src.agents.technical.subdomains.signal_fusion`

- `CAPABILITY_CYCLE` -> `src.agents.technical.subdomains.regime` at `finance-agent-core/src/agents/technical/subdomains/signal_fusion/application/fusion_runtime_service.py:15`. Break the capability cycle through a stable contract or workflow orchestration.


### [TECHNICAL-CAP-VERIFICATION] Module remediation

#### `src.agents.technical.subdomains.verification.application.verification_runtime_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.domain` at `finance-agent-core/src/agents/technical/subdomains/verification/application/verification_runtime_service.py:9`. Expose the required contract through the capability facade.


### [TECHNICAL-CORE] Module remediation

#### `src.agents.technical.application.factory`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/application/factory.py:24`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.fracdiff_runtime_contracts`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.domain` at `finance-agent-core/src/agents/technical/application/fracdiff_runtime_contracts.py:6`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.fracdiff_runtime_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.domain` at `finance-agent-core/src/agents/technical/application/fracdiff_runtime_service.py:15`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.orchestrator`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/application/orchestrator.py:26`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.semantic_backtest_context_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/application/semantic_backtest_context_service.py:18`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.semantic_pipeline_service`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.interpretation.domain` at `finance-agent-core/src/agents/technical/application/semantic_pipeline_service.py:32`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.state_updates`

- `LAYER_DIRECTION` -> `src.workflow.state` at `finance-agent-core/src/agents/technical/application/state_updates.py:8`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.agents.technical.application.subgraph`

- `LAYER_DIRECTION` -> `src.workflow.nodes.technical_analysis.nodes` at `finance-agent-core/src/agents/technical/application/subgraph.py:9`. Move the dependency behind an inward-facing contract or relocate the behavior.
- `LAYER_DIRECTION` -> `src.workflow.nodes.technical_analysis.subgraph_state` at `finance-agent-core/src/agents/technical/application/subgraph.py:19`. Move the dependency behind an inward-facing contract or relocate the behavior.

#### `src.agents.technical.application.use_cases.run_data_fetch_use_case`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.multi_timeframe_fetch_service` at `finance-agent-core/src/agents/technical/application/use_cases/run_data_fetch_use_case.py:17`. Expose the required contract through the capability facade.
- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.market_data.application.ports` at `finance-agent-core/src/agents/technical/application/use_cases/run_data_fetch_use_case.py:21`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.use_cases.run_fusion_compute_use_case`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.calibration.domain` at `finance-agent-core/src/agents/technical/application/use_cases/run_fusion_compute_use_case.py:39`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.use_cases.run_verification_compute_use_case`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.domain` at `finance-agent-core/src/agents/technical/application/use_cases/run_verification_compute_use_case.py:23`. Expose the required contract through the capability facade.

#### `src.agents.technical.application.wiring`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.features.infrastructure` at `finance-agent-core/src/agents/technical/application/wiring.py:20`. Expose the required contract through the capability facade.

#### `src.agents.technical.interface.serializers`

- `CAPABILITY_PRIVATE_IMPORT` -> `src.agents.technical.subdomains.verification.domain` at `finance-agent-core/src/agents/technical/interface/serializers.py:15`. Expose the required contract through the capability facade.
