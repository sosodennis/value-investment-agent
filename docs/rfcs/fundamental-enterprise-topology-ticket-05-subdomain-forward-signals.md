# Ticket 05: Enterprise Topology — forward_signals 移入 subdomains

## 目標

將 `forward_signals` 子域移入 `fundamental/subdomains/`，完成所有 import 更新。

## 範圍

- `fundamental/forward_signals/**` → `fundamental/subdomains/forward_signals/**`
- 更新全庫對 `src.agents.fundamental.forward_signals.*` 的引用。

## 依賴

- Ticket 01、02 完成。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/forward_signals/**`
- `finance-agent-core/src/agents/fundamental/application/wiring.py`
- `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/**`

## 實作步驟

1. 移動 `forward_signals` 目錄至 `subdomains/`。
2. 更新全庫 import 至 `src.agents.fundamental.subdomains.forward_signals.*`。
3. legacy import sweep 清除舊路徑引用。

## 驗收標準

- 無任何 `src.agents.fundamental.forward_signals.*` 舊路徑引用。
- 子域位於 `fundamental/subdomains/forward_signals/`。

## 驗證

- `rg "agents\.fundamental\.forward_signals"` 僅指向新路徑。
- 建議跑 forward_signals 相關測試子集。

## 回退策略

- 若需回退，回滾此子域移動與 import 更新。
