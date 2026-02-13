# Sub-Agent Boundary Audit (Based on Package Guideline)
Date: 2026-02-13
Status: Active assessment
Scope: `finance-agent-core` sub-agents (`fundamental`, `news`, `technical`, `debate`)
Reference: `/Users/denniswong/Desktop/Project/value-investment-agent/docs/sub-agent-package-architecture-guideline.md`

## 1. Summary

Current architecture is functionally improved (typed envelope, ports, parser-first), but package ownership is still mixed.

Main risk:
1. Engineers still need to reason about placement manually because some files combine domain + application + interface concerns.
2. Centralized cross-agent files hide ownership boundaries.

## 2. Findings (ordered by severity)

## P0: Layer direction violation in model selection

1. `fundamental` model selection imports adapter from services/data side:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/fundamental_analysis/tools/model_selection.py:12`

Why ambiguous:
1. This file behaves like domain/application policy, but now depends on repository-adjacent adapter types from `src/services`.

Recommendation:
1. Move report extraction adapter into fundamental application/domain-owned module (e.g. `agents/fundamental/application/report_adapter.py`).
2. Keep `services/domain_artifact_ports.py` for persistence concerns only.

## P0: Global contract ownership is centralized, not agent-owned

2. All agent artifact contracts live in one file:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifact_domain_models.py`

Why ambiguous:
1. Ownership of news/debate/technical/fundamental contracts is not explicit by package.

Recommendation:
1. Split by agent interface package:
   - `agents/fundamental/interface/contracts.py`
   - `agents/news/interface/contracts.py`
   - `agents/technical/interface/contracts.py`
   - `agents/debate/interface/contracts.py`
2. Keep shared envelope only in shared interface.

## P1: Global ports file mixes all agents

3. Single file defines all ports:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/domain_artifact_ports.py:143`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/domain_artifact_ports.py:235`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/domain_artifact_ports.py:324`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/domain_artifact_ports.py:485`

Why ambiguous:
1. It weakens per-agent ownership and increases merge conflicts.

Recommendation:
1. Keep generic `TypedArtifactPort` in shared/data.
2. Move concrete per-agent ports into each agent package.

## P1: Node files are still multi-concern (orchestration + mapping + serialization)

4. `financial_news_research/nodes.py` mixes fallback resolution, contract creation, LLM orchestration, and persistence:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/nodes.py:52`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/nodes.py:156`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/nodes.py:649`

5. `technical_analysis/nodes.py` contains data-shape conversion helpers (`safe_float`) inline:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/nodes.py:228`

6. `debate/nodes.py` handles prompt orchestration + compression + artifact transform in one file:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/nodes.py:55`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/nodes.py:231`

Recommendation:
1. Move transformation/serialization helpers into interface/application services.
2. Keep nodes as thin orchestration shell.

## P1: Preview mappers contain business-derived calculations

7. `summarize_fundamental_for_preview` calculates ROE and formats values:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/fundamental_analysis/mappers.py:7`

8. Similar preview logic exists for other agents:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/mappers.py:7`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/mappers.py:9`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/mappers.py:6`

Why ambiguous:
1. Some logic is pure display, some is business-derived.

Recommendation:
1. Split into:
   - application/view-model builder (business-derived fields)
   - interface/display formatter (string/emoji formatting)

## P2: Tools directories still mix pure math and external I/O semantics

9. Example mixed area in technical and debate toolsets:
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/tools/*`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/tools/*`

Recommendation:
1. Move provider calls to `data/clients`.
2. Move deterministic calculations to `domain/services`.

## 3. Per-Agent Placement Hotspots

## Fundamental

Likely unclear placement:
1. `tools/model_selection.py` currently policy + adapter dependency.
2. `mappers.py` has both derived metrics and display formatting.

## News

Likely unclear placement:
1. `nodes.py` has ticker fallback + selection fallback + DTO packaging.
2. `structures.py` mixes rich contract semantics and AI enrichment details.

## Technical

Likely unclear placement:
1. `nodes.py` has inline conversion/serialization utilities.
2. `tools/` mixes compute and provider concerns.

## Debate

Likely unclear placement:
1. Very large `nodes.py` acts as orchestrator + transformer + report packager.
2. `structures.py` can be split into domain conclusion model vs interface contract model.

## 4. Will this cause future development friction?

Yes, if left as is, engineers will still spend placement time in these areas:
1. deciding whether a new helper belongs in nodes, mappers, tools, or interface.
2. deciding whether cross-agent contract updates belong in global file or agent file.

Friction will decrease significantly after two structural moves:
1. Agent-owned interface contracts split from global model file.
2. Per-agent ports and adapters moved out of one global services file.

## 5. Concrete Next Refactor Slices

1. Slice A (highest ROI):
   - Extract `FundamentalReportsAdapter` out of `src/services` into fundamental application module.
   - Remove `model_selection.py` dependency on `src/services`.

2. Slice B:
   - Split `artifact_domain_models.py` into per-agent interface contract modules.
   - Keep only envelope/base primitives in shared interface.

3. Slice C:
   - Split `domain_artifact_ports.py` into shared generic base + per-agent ports.

4. Slice D:
   - Split preview logic into "derive" and "format" layers.

## 6. Decision Confidence

Overall confidence: high.

Reason:
1. Findings are based on concrete current files and import/runtime responsibilities.
2. Recommendations align with your zero-compat, contract-first policy and reduce future placement ambiguity.
