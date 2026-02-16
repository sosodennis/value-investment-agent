# Simple Triad Layer Alignment (Per-Agent Audit)
Date: 2026-02-16
Scope: `finance-agent-core/src/agents/*`, `finance-agent-core/src/workflow/**`
Policy: strict naming + strict ownership aligned to the three mapping boundaries.

Status Update (2026-02-16):

1. News agent duplicate `application/parsers.py` and `application/prompt_formatters.py` have been removed.
2. News boundary shape logic now uses interface-layer SSOT implementations.
3. Intent candidate prompt + serialization path now uses domain prompt builder and interface serializer through orchestrator.
4. News prompt policy now lives in `news/domain/prompt_builder.py`; workflow reads domain prompt specs.
5. Debate prompt policy has been moved from workflow layer to `debate/domain/prompt_builder.py`.
6. Debate LLM response boundary now uses typed protocol (`response.content`) instead of duck-typing fallback.
7. Debate node execution flow is now centralized in `debate/application/orchestrator.py`; workflow nodes are thin routers.
8. Debate dependency composition has been moved from workflow node to `debate/application/factory.py`.
9. Fundamental workflow dependency composition has been moved to `fundamental/application/factory.py`.
10. Technical workflow dependency composition has been moved to `technical/application/factory.py`.
11. News workflow dependency composition has been moved to `news/application/factory.py`.
12. Intent orchestrator dependency composition has been moved to `intent/application/factory.py`.
13. Intent clarification resolution mapping has been moved from workflow node into `intent/application/orchestrator.py`.
14. News selector/fetch search-result payloads now pass through interface parser validation (`news/interface/parsers.py`) before application logic.
15. News prompt transport formatting now uses `news/interface/prompt_renderers.py` as the named renderer boundary.
16. Debate verdict normalization (history text, citation audit payload, final update mapping) now lives in `debate/interface/mappers.py`.
17. Debate workflow nodes no longer import domain prompt constants; prompt config is routed via `debate/application/factory.py`.
18. Technical prompt policy has been moved to `technical/domain/prompt_builder.py`; runtime semantic layer now consumes domain prompt specs.
19. Fundamental cross-agent context mapping has been moved to `fundamental/interface/mappers.py::build_mapper_context`.
20. Fundamental model-selection details serialization has been moved to `fundamental/interface/serializers.py::serialize_model_selection_details`.
21. Fundamental valuation execution now validates skill runtime and calculator output through typed interface parsers (`fundamental/interface/parsers.py`).
22. News analyzer/aggregator input now enforces typed interface parsing for stored news items (`news/interface/parsers.py::parse_news_items`).
23. Technical progress preview payload assembly now belongs to interface serializers (`technical/interface/serializers.py`), with application orchestrator delegating to serializer functions.
24. Debate compressed cross-agent report payload mapping now delegates to interface serializer (`debate/interface/serializers.py::build_compressed_report_payload`).
25. Incident fix: debate source reader now converts `FinancialReportsArtifactData.financial_reports` to JSON dict at boundary (`debate/data/report_reader.py`) to prevent model/dict mixed-flow runtime crashes.

## 1. The Simple Triad (Authoritative)

All cross-boundary mapping should be explainable by exactly one of these:

1. Request/Response mapping:
   - external API/SSE/request DTO <-> domain/application objects
2. Local Store mapping:
   - persisted artifact/storage DTO <-> domain/application objects
3. Cross-Agent contract mapping:
   - internal agent context/contracts <-> domain/application objects

If a mapping does not fit one of these three, it is likely misplaced.

## 2. Strict Naming Rules

## 2.1 Request/Response mapping

Required locations:

1. `src/interface/events/*.py`
2. `src/agents/*/interface/contracts.py`
3. `src/agents/*/interface/{parsers,serializers,mappers}.py`

Forbidden:

1. ad-hoc request/response shape conversion in `workflow/nodes/**`

## 2.2 Local Store mapping

Required locations:

1. `src/agents/*/data/ports.py`
2. `src/agents/*/data/mappers.py`
3. `src/shared/cross_agent/data/typed_artifact_port.py`

Forbidden:

1. direct storage payload normalization in workflow nodes

## 2.3 Cross-Agent contract mapping

Required locations:

1. `src/interface/artifacts/artifact_contract_registry.py`
2. `src/agents/*/interface/contracts.py`
3. `src/agents/*/interface/{parsers,serializers,mappers}.py`

Forbidden:

1. legacy fallback shape conversion in cross-agent workflow paths
2. duplicate parser implementations in different layers

## 2.4 Incident Note (Debate Crash)

Context:

1. Date: 2026-02-16.
2. Symptom: debate aggregator crashed with `AttributeError: 'FinancialReportModel' object has no attribute 'get'`.

Violation against this guideline:

1. Violated Rule 2: cross-agent contract path expected JSON DTO (`dict`) but received Pydantic model.
2. Violated Rule 3: boundary conversion was not completed once at adapter boundary, causing mixed model/dict flow downstream.

Root cause:

1. `debate/data/report_reader.py` returned `payload.financial_reports` (typed model list) directly.
2. `debate/domain/services.py::compress_financial_data` expects dict-style access with `.get(...)`.

Corrective action:

1. Enforce one-time conversion at boundary: model -> JSON dict before returning from report reader.
2. Keep downstream domain/application code on one representation only for that flow.

## 3. Per-Agent Analysis

## 3.1 Intent Agent

Strengths:

1. Domain VO and interface DTO are separated (`TickerCandidate` vs `TickerCandidateModel`).
2. Candidate serialization now goes through interface serializer.

Gaps:

1. No critical triad gap found in current intent flow after clarification mapping handoff to orchestrator.

Priority:

1. Low

## 3.2 Fundamental Agent

Strengths:

1. Interface serializers/mappers are established.
2. Data/store mapping via typed ports is present.

Gaps:

1. No critical triad gap found in current fundamental flow after mapper/serializer/parser boundary split.

Priority:

1. Low

## 3.3 News Agent

Strengths:

1. Interface contracts/serializers exist and are actively used.
2. Orchestrator-based flow is clear.

Gaps:

1. No critical triad gap found in selector/fetch boundaries after parser-enforced typed validation.

Priority:

1. Low

## 3.4 Technical Agent

Strengths:

1. Interface serializers/mappers exist and are used.
2. Technical orchestrator centralizes most flow.

Gaps:

1. No critical triad gap found in prompt ownership after moving prompt policy into domain builder.

Priority:

1. Low

## 3.5 Debate Agent

Strengths:

1. Final report serialization now has dedicated interface serializer.
2. Debate interface contract path is present.

Gaps:

1. No critical triad gap found in verdict normalization path after interface mapper split.

Priority:

1. Low

## 4. Consolidation Plan (Strict)

1. Keep workflow nodes as thin router shells:
   - only call application orchestrator/service entrypoints
2. Keep exactly one parser/serializer/mapper implementation per boundary concern:
   - interface as SSOT for boundary shape logic
3. Enforce triad ownership in PR review:
   - every new mapping function must declare triad type in docstring
4. Remove duplicated modules once call sites are migrated.

## 5. Definition of Done

1. No workflow node contains business mapping logic.
2. No duplicate parser/formatter for the same boundary across application/interface.
3. Every mapping function can be tagged as one of:
   - request/response
   - local store
   - cross-agent contract
