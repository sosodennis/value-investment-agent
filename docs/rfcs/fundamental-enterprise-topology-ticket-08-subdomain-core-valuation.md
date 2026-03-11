# Ticket 08: Enterprise Topology — core_valuation 移入 subdomains

## 目標

將 `core_valuation` 子域移入 `fundamental/subdomains/`，完成所有 import 更新。

## 範圍

- `fundamental/core_valuation/**` → `fundamental/subdomains/core_valuation/**`
- 更新全庫對 `src.agents.fundamental.core_valuation.*` 的引用。

## 依賴

- Ticket 01、02 完成。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/core_valuation/**`
- `finance-agent-core/src/agents/fundamental/application/workflow_orchestrator/**`
- `finance-agent-core/src/agents/fundamental/subdomains/model_selection/**`（若 model_selection 已遷移）

## 實作步驟

1. 移動 `core_valuation` 目錄至 `subdomains/`。
2. 更新全庫 import 至 `src.agents.fundamental.subdomains.core_valuation.*`。
3. legacy import sweep 清除舊路徑引用。

## 驗收標準

- 無任何 `src.agents.fundamental.core_valuation.*` 舊路徑引用。
- 子域位於 `fundamental/subdomains/core_valuation/`。

## 驗證

- `rg "agents\.fundamental\.core_valuation"` 僅指向新路徑。

## 回退策略

- 若需回退，回滾此子域移動與 import 更新。
