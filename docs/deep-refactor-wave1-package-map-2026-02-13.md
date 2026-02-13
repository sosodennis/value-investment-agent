# Deep Refactor Wave 1 Package Map
Date: 2026-02-13
Status: Historical baseline map (non-normative)

This file records Wave 1 planning/mapping state.
Some references are intentionally pre-cutover snapshots.

## 1. Created Skeleton Packages

`finance-agent-core/src/shared/`
1. `domain/`
2. `application/`
3. `data/`
4. `interface/`

`finance-agent-core/src/agents/fundamental/`
1. `domain/`
2. `application/`
3. `data/`
4. `interface/`

`finance-agent-core/src/agents/news/`
1. `domain/`
2. `application/`
3. `data/`
4. `interface/`

`finance-agent-core/src/agents/technical/`
1. `domain/`
2. `application/`
3. `data/`
4. `interface/`

`finance-agent-core/src/agents/debate/`
1. `domain/`
2. `application/`
3. `data/`
4. `interface/`

## 2. Mapping Table (Current -> Target)

1. `src/interface/artifact_domain_models.py`
   - target split to `src/agents/*/interface/contracts.py`
2. `src/services/domain_artifact_ports.py`
   - generic base to `src/shared/data/typed_artifact_port.py`
   - per-agent ports to `src/agents/*/data/ports.py`
3. `src/workflow/nodes/fundamental_analysis/*`
   - domain/policies to `src/agents/fundamental/domain|application`
   - interface contracts/parsers to `src/agents/fundamental/interface`
4. `src/workflow/nodes/financial_news_research/*`
   - equivalent split to `src/agents/news/*`
5. `src/workflow/nodes/technical_analysis/*`
   - equivalent split to `src/agents/technical/*`
6. `src/workflow/nodes/debate/*`
   - equivalent split to `src/agents/debate/*`

## 3. Wave 1 Exit Rule

Wave 1 is complete when skeleton exists and all next-wave target files have clear destination mapping.
