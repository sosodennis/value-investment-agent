# RFC: Fundamental 垂直切片重構計劃（2026-03-11）

## Requirement Breakdown

- **Objective**: 以方案 B（垂直切片）重構 `fundamental`，將單體流程拆為多個子域模組，每個子域內含 `application/domain/infrastructure/interface`，由薄的 `workflow_orchestrator` 統一編排。
- **Constraints**:
  - 不保留任何相容層或 re-export；完成切片後舊路徑必須移除。
  - 在重構過程中清除 legacy、compat、未被引用的舊代碼。
  - 需要同步更新其他 agents/流程節點對 fundamental 的 import/契約依賴。
- **Non-goals**: 不改變估值算法與對外行為、不引入新功能、不替換外部資料來源。

## Technical Objectives and Strategy

- **垂直切片**：子域化 `core_valuation`、`financial_statements`、`forward_signals`、`model_selection`、`market_data`、`artifacts_provenance`、`workflow_orchestrator`。
- **共享契約**：`TraceableField/Provenance` 放在 `fundamental/shared/contracts/traceable.py` 作為 shared kernel，供多子域依賴。
- **流程層瘦身**：`workflow_orchestrator` 僅負責狀態轉移與調度，不承擔領域邏輯。
- **無兼容層**：移動後更新全部 import；舊路徑不保留 shim。
- **同步更新**：所有引用 fundamental 舊路徑的 agent/workflow/tests 一律更新。

## Involved Files

**核心入口與流程**
- `finance-agent-core/src/agents/fundamental/subgraph.py`
- `finance-agent-core/src/agents/fundamental/wiring.py`
- `finance-agent-core/src/agents/fundamental/application/factory.py`
- `finance-agent-core/src/agents/fundamental/application/orchestrator.py`
- `finance-agent-core/src/agents/fundamental/application/ports.py`
- `finance-agent-core/src/agents/fundamental/application/state_readers.py`
- `finance-agent-core/src/agents/fundamental/application/state_updates.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_financial_health_use_case.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_model_selection_use_case.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`

**domain**
- `finance-agent-core/src/agents/fundamental/domain/model_selection.py`
- `finance-agent-core/src/agents/fundamental/domain/model_selection_*`
- `finance-agent-core/src/agents/fundamental/domain/valuation_model_type_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/**`

**infrastructure**
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/**`
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/**`
- `finance-agent-core/src/agents/fundamental/infrastructure/artifacts/**`

**interface**
- `finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `finance-agent-core/src/agents/fundamental/interface/parsers.py`
- `finance-agent-core/src/agents/fundamental/interface/serializers.py`
- `finance-agent-core/src/agents/fundamental/interface/mappers.py`
- `finance-agent-core/src/agents/fundamental/interface/report_projection_service.py`

**外部依賴更新**
- `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py`
- `finance-agent-core/src/workflow/nodes/fundamental_analysis/subgraph_state.py`
- `finance-agent-core/src/workflow/graph.py`
- `finance-agent-core/src/agents/debate/application/debate_context.py`
- 全庫引用 `agents.fundamental` 的測試與其他模組（需 `rg` 清點）

## Detailed Per-File Plan

### A) 舊 -> 新路徑映射表（核心）

| 舊路徑 | 新路徑 | 備註 |
| --- | --- | --- |
| `agents/fundamental/application/use_cases/run_financial_health_use_case.py` | `agents/fundamental/workflow_orchestrator/application/financial_health_flow.py` | 流程入口遷移，邏輯拆分到 `financial_statements` 與 `forward_signals` 子域服務 |
| `agents/fundamental/application/use_cases/run_model_selection_use_case.py` | `agents/fundamental/workflow_orchestrator/application/model_selection_flow.py` | 核心規則移到 `model_selection` 子域 |
| `agents/fundamental/application/use_cases/run_valuation_use_case.py` | `agents/fundamental/workflow_orchestrator/application/valuation_flow.py` + `agents/fundamental/core_valuation/**` | flow 變薄；估值核心下沉 |
| `agents/fundamental/domain/valuation/**` | `agents/fundamental/core_valuation/domain/**` | valuation runtime, parameterization, policies, calculators |
| `agents/fundamental/domain/valuation_model_type_service.py` | `agents/fundamental/core_valuation/domain/valuation_model_type_service.py` | 估值模型型別解析 |
| `agents/fundamental/domain/model_selection*` | `agents/fundamental/model_selection/domain/**` | scoring / spec / reasoning |
| `agents/fundamental/interface/report_projection_service.py` | `agents/fundamental/model_selection/interface/report_projection_service.py` | model selection 專用 projection |
| `agents/fundamental/infrastructure/sec_xbrl/**` | `agents/fundamental/financial_statements/infrastructure/sec_xbrl/**` | XBRL extraction / reports canonicalization |
| `agents/fundamental/infrastructure/sec_xbrl/forward_signals_*` | `agents/fundamental/forward_signals/infrastructure/**` | text pipeline / finbert / signal extraction |
| `agents/fundamental/infrastructure/market_data/**` | `agents/fundamental/market_data/infrastructure/**` | market data providers/snapshot |
| `agents/fundamental/infrastructure/artifacts/**` | `agents/fundamental/artifacts_provenance/infrastructure/**` | artifact repository |
| `agents/fundamental/interface/contracts.py` | `agents/fundamental/shared/contracts/traceable.py` + `agents/fundamental/artifacts_provenance/interface/contracts.py` | Traceable/Provenance 移 shared；其餘合約拆分 |
| `agents/fundamental/interface/parsers.py` | `agents/fundamental/financial_statements/interface/parsers.py` | 財報解析契約 |
| `agents/fundamental/interface/serializers.py` | `agents/fundamental/artifacts_provenance/interface/serializers.py` | artifact 相關序列化 |
| `agents/fundamental/interface/mappers.py` | `agents/fundamental/workflow_orchestrator/interface/mappers.py` | 進度/preview 對應到流程層 |
| `agents/fundamental/application/state_readers.py` | `agents/fundamental/workflow_orchestrator/application/state_readers.py` | state 讀取集中在流程層 |
| `agents/fundamental/application/state_updates.py` | `agents/fundamental/workflow_orchestrator/application/state_updates.py` | state 更新集中在流程層 |
| `agents/fundamental/application/ports.py` | 子域內 `application/ports.py` | 依子域拆分 ports |
| `agents/fundamental/application/factory.py` | `agents/fundamental/workflow_orchestrator/application/factory.py` + 子域 factories | DI 入口拆分 |
| `agents/fundamental/wiring.py` | `agents/fundamental/wiring.py` | 保留根 wiring 組合子域 |
| `agents/fundamental/subgraph.py` | `agents/fundamental/subgraph.py` | 更新 import 指向新流程入口 |

### B) 切片拆分（6 張 tickets）

**Ticket 1: 垂直切片骨架與 shared contracts**
- 建立 `shared/contracts/traceable.py` 作為唯一 Traceable/Provenance 來源。
- 建立所有子域目錄與 `application/domain/infrastructure/interface` 架構空殼。
- 更新所有 Traceable/Provenance 相關 import。
- 移除舊路徑中 traceable 定義。
- Exit: Traceable/Provenance 單一來源，無舊路徑殘留。

**Ticket 2: market_data 子域化**
- 遷移 `infrastructure/market_data/**` 到 `market_data/infrastructure/**`。
- 建立 `market_data/application` 封裝 snapshot 生成服務。
- 更新所有引用 market_data 的 import。
- 清除 legacy/unused provider（以 `rg` 與測試覆蓋確認）。
- Exit: market_data 完全由子域提供，舊路徑移除。

**Ticket 3: financial_statements 子域化**
- 遷移 `sec_xbrl/**` 到 `financial_statements/infrastructure/**`（不含 forward_signals）。
- `interface/parsers.py` 移到 `financial_statements/interface/parsers.py`。
- 更新相關 contracts/ports。
- 清除未被使用的 XBRL helpers。
- Exit: XBRL/報表處理只在 financial_statements 子域。

**Ticket 4: forward_signals 子域化**
- 遷移 forward signal pipeline（text/finbert/scoring/calibration）到 `forward_signals` 子域。
- 更新依賴路徑與 contracts。
- 清除舊的信號解析或兼容邏輯。
- Exit: forward_signals 成為獨立子域，舊路徑移除。

**Ticket 5: model_selection 子域化**
- 遷移 `domain/model_selection*` 到 `model_selection/domain/**`。
- `report_projection_service.py` 與相關 interface/contract 進入 `model_selection/interface/**`。
- 更新 model selection 的 import 與 DI。
- 清理未引用的 scoring/spec 規則。
- Exit: model_selection 子域獨立，可單獨測試。

**Ticket 6: core_valuation + workflow_orchestrator 重整**
- `domain/valuation/**` 移至 `core_valuation/domain/**`。
- `run_valuation_use_case.py` 拆薄為 `workflow_orchestrator/application/valuation_flow.py` + core_valuation 服務。
- `run_financial_health_use_case.py` / `run_model_selection_use_case.py` 轉為 `workflow_orchestrator` flows。
- `application/state_readers.py` / `state_updates.py` 移入 `workflow_orchestrator`。
- 更新 `subgraph.py`、workflow nodes、debate context、其他 agents import。
- 全面移除舊路徑殘留。
- Exit: 全部流程走新子域；無 compat code。

### C) Legacy/Unused 清理策略

- 使用 `rg "legacy|compat|deprecated|TODO: remove"` 掃描。
- 使用 `rg "agents\.fundamental"` 與 `rg "fundamental"` 進行引用清點。
- 對疑似未使用模組，使用測試或執行流程驗證後移除。
- 清理行為必須跟隨切片，不留到最後集中處理。

## Risk/Dependency Assessment

- **風險**: import path 大量變動，容易出現 runtime failure。
- **風險**: Traceable/Provenance 若分散，會破壞審計與序列化一致性。
- **風險**: `run_valuation_use_case.py` 拆分過程中行為偏差。
- **依賴**: workflow nodes / debate context / state contracts 需要同步更新。
- **回退**: 無 compat code，回退依賴 git revert 或分支回滾。

## Validation and Rollout Gates

- 每個 ticket 完成後必須通過 lint/typecheck（若專案已有標準）。
- 針對每個子域至少建立一個最小單元測試或 contract 驗證。
- Ticket 6 之前可維持部分流程在舊路徑，但在 Ticket 6 結束前必須全部切換。
- 完成後必須跑一輪完整 fundamental flow 回歸測試。

## Assumptions/Open Questions

- 是否允許為 shared kernel 引入 `fundamental/shared/`（已確認允許）。
- 子域內 `application` 的命名與結構由重構時定義細節。
- CI 是否已有統一的 lint/test pipeline（若無，需補足最小可驗證方案）。
- 舊版流程能否在中期仍被調用（目前要求無 compat code，需嚴格遷移節奏）。
