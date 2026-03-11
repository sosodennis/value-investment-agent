# Ticket 03: Enterprise Topology — artifacts_provenance 移入 subdomains

## 目標

將 `artifacts_provenance` 子域移入 `fundamental/subdomains/`，完成所有 import 更新。

## 範圍

- `fundamental/artifacts_provenance/**` → `fundamental/subdomains/artifacts_provenance/**`
- 更新全庫對 `src.agents.fundamental.artifacts_provenance.*` 的引用。

## 依賴

- Ticket 01、02 完成（root 結構已建立）。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/artifacts_provenance/**`
- `finance-agent-core/src/agents/fundamental/application/wiring.py`
- `finance-agent-core/src/agents/fundamental/interface/workflow_orchestrator/**`

## 實作步驟

1. 移動 `artifacts_provenance` 目錄至 `subdomains/`。
2. 更新所有 import 指向 `src.agents.fundamental.subdomains.artifacts_provenance.*`。
3. legacy import sweep 清除舊路徑引用。

## 驗收標準

- 無任何 `src.agents.fundamental.artifacts_provenance.*` 舊路徑引用。
- 子域位於 `fundamental/subdomains/artifacts_provenance/`。

## 驗證

- `rg "agents\.fundamental\.artifacts_provenance"` 僅指向新路徑。

## 回退策略

- 若需回退，回滾此子域移動與 import 更新。
