# Ticket 06: core_valuation + workflow_orchestrator 重整

## 目標

將估值核心下沉到 `core_valuation` 子域，流程編排集中到 `workflow_orchestrator`，並更新所有外部依賴 import，移除所有舊路徑。

## 範圍

- 遷移 `domain/valuation/**` 到 `core_valuation/domain/**`。
- 拆薄 `run_valuation_use_case.py`、`run_financial_health_use_case.py`、`run_model_selection_use_case.py` 到 `workflow_orchestrator/application/*`。
- `state_readers.py` / `state_updates.py` 進入 `workflow_orchestrator/application`。
- 更新 `subgraph.py`、workflow nodes、debate context 等外部依賴。
- 全面移除舊路徑與 compat code。

## 依賴

- Ticket 01 完成。
- Ticket 02-05 完成。

## 主要影響檔案

- 舊 `finance-agent-core/src/agents/fundamental/application/use_cases/*`
- 舊 `finance-agent-core/src/agents/fundamental/domain/valuation/**`
- 新 `finance-agent-core/src/agents/fundamental/core_valuation/**`
- 新 `finance-agent-core/src/agents/fundamental/workflow_orchestrator/**`
- `finance-agent-core/src/agents/fundamental/subgraph.py`
- `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py`
- `finance-agent-core/src/workflow/nodes/fundamental_analysis/subgraph_state.py`
- `finance-agent-core/src/workflow/graph.py`
- `finance-agent-core/src/agents/debate/application/debate_context.py`

## 實作步驟

1. 遷移 valuation domain 到 core_valuation。
2. 將三個 use case flow 拆薄後放入 workflow_orchestrator。
3. 更新 wiring/factory/ports 組合關係。
4. 更新 workflow nodes 與下游 agent import。
5. 移除所有舊路徑與 compat 代碼。
6. 清理未使用/legacy 模組。

## 驗收標準

- 所有流程都使用新子域路徑。
- 舊路徑無任何殘留檔案或 import。
- end-to-end fundamental flow 通過。

## 驗證

- `rg "agents\.fundamental"` 不應指向舊路徑。
- 完整 fundamental flow 回歸測試可執行。

## 回退策略

- git revert 或回滾至前一切片。
