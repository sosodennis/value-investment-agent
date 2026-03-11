# Ticket 04: Enterprise Topology — financial_statements 移入 subdomains

## 目標

將 `financial_statements` 子域移入 `fundamental/subdomains/`，完成所有 import 更新。

## 範圍

- `fundamental/financial_statements/**` → `fundamental/subdomains/financial_statements/**`
- 更新全庫對 `src.agents.fundamental.financial_statements.*` 的引用。

## 依賴

- Ticket 01、02 完成。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/financial_statements/**`
- `finance-agent-core/src/interface/artifacts/artifact_data_models.py`
- `finance-agent-core/src/agents/fundamental/application/wiring.py`
- `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/**`

## 實作步驟

1. 移動 `financial_statements` 目錄至 `subdomains/`。
2. 更新全庫 import 至 `src.agents.fundamental.subdomains.financial_statements.*`。
3. legacy import sweep 清除舊路徑引用。

## 驗收標準

- 無任何 `src.agents.fundamental.financial_statements.*` 舊路徑引用。
- 子域位於 `fundamental/subdomains/financial_statements/`。

## 驗證

- `rg "agents\.fundamental\.financial_statements"` 僅指向新路徑。
- 建議跑 `test_sec_xbrl_*` 相關測試子集。

## 回退策略

- 若需回退，回滾此子域移動與 import 更新。
